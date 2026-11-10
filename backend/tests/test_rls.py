"""Which rows each caller sees once RLS is on (0027), against the live compose Postgres.

Everything runs in one transaction that is rolled back, so the people and rows made here never land.
"""

import json
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import errors
from psycopg.errors import InsufficientPrivilege
from psycopg.rows import dict_row

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

pytestmark = pytest.mark.integration


@pytest.fixture
def db():
    try:
        connection = psycopg.connect(DSN, connect_timeout=3, row_factory=dict_row)
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    with connection, connection.transaction(force_rollback=True):
        yield connection, _world(connection)


def _world(conn) -> dict:
    """Org A and B, a hidden org, one person per role, and a private row of each kind for Org A."""

    def one(sql, params=()):
        return conn.execute(sql, params).fetchone()

    tag = uuid4().hex[:8]
    a = one("INSERT INTO orgs (slug, name) VALUES (%s, 'A') RETURNING id", (f"rls-a-{tag}",))["id"]
    b = one("INSERT INTO orgs (slug, name) VALUES (%s, 'B') RETURNING id", (f"rls-b-{tag}",))["id"]
    hidden = one(
        "INSERT INTO orgs (slug, name, registry_status) VALUES (%s, 'H', 'hidden') RETURNING id",
        (f"rls-h-{tag}",),
    )["id"]

    people = {}
    for name, staff in [("member_a", False), ("steward_a", False), ("admin_a", False), ("member_b", False),
                        ("nobody", False), ("staff", True)]:
        auth_id, email = uuid4(), f"{name}-{tag}@rls.test"
        user_id = one(
            "INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, %s) RETURNING id",
            (email, auth_id, staff),
        )["id"]
        people[name] = {"user_id": user_id, "sub": str(auth_id), "email": email}
    for name, org, role in [("member_a", a, "member"), ("steward_a", a, "steward"), ("admin_a", a, "admin"),
                            ("member_b", b, "member")]:
        conn.execute("INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, %s)",
                     (people[name]["user_id"], org, role))

    conn.execute("INSERT INTO org_tags (org_id, tag_id) SELECT %s, id FROM tags LIMIT 1", (hidden,))
    contact = one("INSERT INTO contacts (org_id, name, is_public) VALUES (%s, 'private', false) RETURNING id",
                  (a,))["id"]
    document = one("INSERT INTO documents (org_id, title, is_public) VALUES (%s, 'vault', false) RETURNING id",
                   (a,))["id"]
    conn.execute("INSERT INTO chunks (document_id, chunk_index, content) VALUES (%s, 0, 'secret')", (document,))
    proposal = one("INSERT INTO proposals (org_id, title) VALUES (%s, 'draft') RETURNING id", (a,))["id"]
    thread = f"rls-{tag}"
    conn.execute("INSERT INTO threads (thread_id, user_id) VALUES (%s, %s)",
                 (thread, people["member_a"]["user_id"]))
    return {"a": a, "b": b, "hidden": hidden, "people": people, "contact": contact,
            "document": document, "proposal": proposal, "thread": thread}


def _as(conn, who: dict | None):
    """Run the rest of the current savepoint as this caller, the way CallerPool does for a request."""
    role, claims = ("anon", "") if who is None else ("authenticated", json.dumps({"sub": who["sub"]}))
    conn.execute("SELECT set_config('role', %s, true), set_config('request.jwt.claims', %s, true)",
                 (role, claims))


def _sees(conn, who, sql, params=()) -> int:
    with conn.transaction(force_rollback=True):
        _as(conn, who)
        return len(conn.execute(sql, params).fetchall())


def _who(world, name):
    return None if name == "anon" else world["people"][name]


@pytest.mark.parametrize(
    "name, expected",
    [("anon", 0), ("nobody", 0), ("member_b", 0), ("member_a", 1), ("steward_a", 1), ("staff", 1)],
)
def test_a_private_contact_document_and_chunk_reach_only_the_org_and_staff(db, name, expected):
    conn, world = db
    who = _who(world, name)
    assert _sees(conn, who, "SELECT 1 FROM contacts WHERE id = %s", (world["contact"],)) == expected
    assert _sees(conn, who, "SELECT 1 FROM documents WHERE id = %s", (world["document"],)) == expected
    assert _sees(conn, who, "SELECT 1 FROM chunks WHERE document_id = %s", (world["document"],)) == expected


@pytest.mark.parametrize(
    "name, expected",
    [("nobody", 0), ("member_b", 0), ("member_a", 1), ("steward_a", 1), ("staff", 1)],
)
def test_a_proposal_reaches_only_the_org_and_staff(db, name, expected):
    conn, world = db
    assert _sees(conn, _who(world, name), "SELECT 1 FROM proposals WHERE id = %s",
                 (world["proposal"],)) == expected


@pytest.mark.parametrize("name, allowed", [("admin_a", True), ("steward_a", True), ("staff", True),
                                           ("member_a", False), ("member_b", False), ("nobody", False)])
def test_only_admins_stewards_and_staff_start_or_edit_a_proposal(db, name, allowed):
    conn, world = db
    who = world["people"][name]
    for sql, params in [("INSERT INTO proposals (org_id, title) VALUES (%s, 'x') RETURNING id", (world["a"],)),
                        ("UPDATE proposals SET title = 'y' WHERE id = %s RETURNING id", (world["proposal"],))]:
        if allowed:
            with conn.transaction(force_rollback=True):
                _as(conn, who)
                assert conn.execute(sql, params).fetchone() is not None
        elif sql.startswith("INSERT"):
            with pytest.raises(InsufficientPrivilege), conn.transaction(force_rollback=True):
                _as(conn, who)
                conn.execute(sql, params)
        else:
            # An update RLS hides changes no row, rather than raising.
            with conn.transaction(force_rollback=True):
                _as(conn, who)
                assert conn.execute(sql, params).fetchone() is None


@pytest.mark.parametrize("name, allowed", [("member_a", True), ("steward_a", True), ("admin_a", True),
                                           ("staff", True), ("member_b", False), ("nobody", False)])
def test_every_role_in_the_org_uploads_to_its_doc_vault(db, name, allowed):
    conn, world = db
    sql = "INSERT INTO documents (org_id, title, is_public) VALUES (%s, 'upload', false) RETURNING id"
    if allowed:
        with conn.transaction(force_rollback=True):
            _as(conn, world["people"][name])
            assert conn.execute(sql, (world["a"],)).fetchone() is not None
    else:
        with pytest.raises(InsufficientPrivilege), conn.transaction(force_rollback=True):
            _as(conn, world["people"][name])
            conn.execute(sql, (world["a"],))


def _deletes(conn, who, doc_type="vault_upload", *, public=False, org=True, world) -> int:
    """How many rows this caller's DELETE of one fresh document removes. RLS refuses with 0, not an error."""
    with conn.transaction(force_rollback=True):
        doc = conn.execute("INSERT INTO documents (org_id, title, doc_type, is_public) VALUES (%s, 'd', %s, %s) "
                           "RETURNING id", (world["a"] if org else None, doc_type, public)).fetchone()["id"]
        _as(conn, who)
        return conn.execute("DELETE FROM documents WHERE id = %s", (doc,)).rowcount


@pytest.mark.parametrize("name, expected", [("staff", 1), ("admin_a", 0), ("member_a", 0), ("steward_a", 0),
                                            ("member_b", 0), ("nobody", 0)])
def test_only_staff_delete_a_vault_upload(db, name, expected):
    conn, world = db
    assert _deletes(conn, world["people"][name], world=world) == expected


@pytest.mark.parametrize("doc_type, public, org", [("annual_report", False, True), ("proposal_draft", True, True),
                                                   ("vault_upload", True, True), ("source_dataset", False, False)])
def test_staff_delete_nothing_but_a_private_org_vault_upload(db, doc_type, public, org):
    conn, world = db
    assert _deletes(conn, world["people"]["staff"], doc_type, public=public, org=org, world=world) == 0


def test_signed_out_cannot_delete_a_document(db):
    conn, world = db
    with pytest.raises(InsufficientPrivilege):
        _deletes(conn, None, world=world)


def test_signed_out_cannot_use_an_org_private_table_at_all(db):
    conn, _ = db
    with pytest.raises(InsufficientPrivilege), conn.transaction(force_rollback=True):
        _as(conn, None)
        conn.execute("SELECT 1 FROM proposals")


@pytest.mark.parametrize("name, expected", [("anon", 0), ("member_a", 0), ("staff", 1)])
def test_a_hidden_org_and_its_rows_reach_only_staff(db, name, expected):
    conn, world = db
    who = _who(world, name)
    assert _sees(conn, who, "SELECT 1 FROM orgs WHERE id = %s", (world["hidden"],)) == expected
    assert _sees(conn, who, "SELECT 1 FROM org_tags WHERE org_id = %s", (world["hidden"],)) == expected


def test_public_rows_are_the_same_signed_out_and_signed_in_with_no_org(db):
    conn, world = db
    for sql in ["SELECT id FROM orgs", "SELECT id FROM contacts", "SELECT id FROM documents",
                "SELECT id FROM programs"]:
        assert _sees(conn, None, sql) == _sees(conn, world["people"]["nobody"], sql), sql


@pytest.mark.parametrize("name, expected", [("member_a", 1), ("member_b", 0), ("staff", 1)])
def test_a_thread_reaches_its_owner_and_staff(db, name, expected):
    conn, world = db
    assert _sees(conn, _who(world, name), "SELECT 1 FROM threads WHERE thread_id = %s",
                 (world["thread"],)) == expected


def test_a_user_sees_only_their_own_user_and_membership_rows(db):
    conn, world = db
    me = world["people"]["member_a"]
    assert _sees(conn, me, "SELECT 1 FROM users") == 1
    assert _sees(conn, me, "SELECT 1 FROM org_members") == 1


@pytest.mark.parametrize(
    "name, expected", [("member_a", 1), ("steward_a", 1), ("member_b", 1), ("admin_a", 3)]
)
def test_only_an_admin_sees_the_rest_of_their_org(db, name, expected):
    conn, world = db
    who = world["people"][name]
    members = f"SELECT 1 FROM org_members WHERE org_id IN ({world['a']}, {world['b']})"
    users = (f"SELECT 1 FROM users u JOIN org_members m ON m.user_id = u.id "
             f"WHERE m.org_id IN ({world['a']}, {world['b']})")
    assert _sees(conn, who, members) == expected
    assert _sees(conn, who, users) == expected


def test_a_steward_cannot_write_to_the_org_it_reads(db):
    conn, world = db
    with pytest.raises(InsufficientPrivilege), conn.transaction(force_rollback=True):
        _as(conn, world["people"]["steward_a"])
        conn.execute("INSERT INTO contacts (org_id, name) VALUES (%s, 'x')", (world["a"],))


def test_a_member_writes_to_their_own_org_and_not_another(db):
    conn, world = db
    with conn.transaction(force_rollback=True):
        _as(conn, world["people"]["member_a"])
        conn.execute("INSERT INTO contacts (org_id, name) VALUES (%s, 'x') RETURNING id", (world["a"],))
    with pytest.raises(InsufficientPrivilege), conn.transaction(force_rollback=True):
        _as(conn, world["people"]["member_a"])
        conn.execute("INSERT INTO contacts (org_id, name) VALUES (%s, 'x')", (world["b"],))


def test_an_import_table_reaches_only_staff(db):
    conn, world = db
    assert _sees(conn, world["people"]["member_a"], "SELECT 1 FROM ingest_runs") == 0
    with conn.transaction(force_rollback=True):
        owner_count = conn.execute("SELECT count(*) AS n FROM ingest_runs").fetchone()["n"]
    assert _sees(conn, world["people"]["staff"], "SELECT 1 FROM ingest_runs") == owner_count


def _call(conn, who, sql, params=()):
    """Run one statement as this caller and roll it back; returns the error class, or None when it worked."""
    try:
        with conn.transaction(force_rollback=True):
            _as(conn, who)
            conn.execute(sql, params)
    except psycopg.Error as exc:
        return type(exc)
    return None



def _add(conn, who, org_id, email, role="member"):
    return _call(conn, who, "SELECT app.add_org_member(%s, %s, %s)", (org_id, email, role))


@pytest.mark.parametrize(
    "name, expected",
    [("admin_a", None), ("staff", None), ("member_a", errors.InsufficientPrivilege),
     ("steward_a", errors.InsufficientPrivilege), ("member_b", errors.InsufficientPrivilege)],
)
def test_only_an_admin_or_staff_manages_an_orgs_members(db, name, expected):
    conn, world = db
    people, a = world["people"], world["a"]
    who, member = people[name], people["member_a"]["user_id"]
    assert _add(conn, who, a, people["nobody"]["email"]) is expected
    assert _call(conn, who, "SELECT app.set_org_member_role(%s, %s, 'steward')", (a, member)) is expected
    assert _call(conn, who, "SELECT app.remove_org_member(%s, %s)", (a, member)) is expected


def test_an_org_keeps_its_last_admin(db):
    conn, world = db
    admin, a = world["people"]["admin_a"], world["a"]
    assert _call(conn, admin, "SELECT app.set_org_member_role(%s, %s, 'member')",
                 (a, admin["user_id"])) is errors.RaiseException
    assert _call(conn, admin, "SELECT app.remove_org_member(%s, %s)", (a, admin["user_id"])) is errors.RaiseException


def test_adding_someone_already_in_the_org_is_refused(db):
    conn, world = db
    people = world["people"]
    assert _add(conn, people["admin_a"], world["a"], people["member_a"]["email"]) is errors.RaiseException


@pytest.mark.parametrize("name", ["admin_a", "staff"])
@pytest.mark.parametrize("users_row", [False, True], ids=["no users row", "users row, never signed in"])
def test_only_someone_who_has_signed_in_can_be_added(db, name, users_row):
    conn, world = db
    email = f"never-{uuid4().hex[:8]}@rls.test"
    if users_row:
        conn.execute("INSERT INTO users (email) VALUES (%s)", (email,))
    assert _add(conn, world["people"][name], world["a"], email) is errors.RaiseException


@pytest.mark.parametrize("role", ["member", "admin"])
def test_an_admin_or_member_belongs_to_one_org_only(db, role):
    conn, world = db
    people = world["people"]
    assert _add(conn, people["admin_a"], world["a"], people["member_b"]["email"], role) is errors.RaiseException


def test_a_steward_may_support_another_org_but_not_join_it(db):
    conn, world = db
    people, a = world["people"], world["a"]
    member_b = people["member_b"]
    with conn.transaction(force_rollback=True):
        _as(conn, people["admin_a"])
        conn.execute("SELECT app.add_org_member(%s, %s, 'steward')", (a, member_b["email"]))
        with pytest.raises(errors.RaiseException), conn.transaction():
            conn.execute("SELECT app.set_org_member_role(%s, %s, 'member')", (a, member_b["user_id"]))


def test_the_index_holds_even_for_the_owner(db):
    conn, world = db
    with pytest.raises(errors.UniqueViolation), conn.transaction(force_rollback=True):
        conn.execute("INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, 'member')",
                     (world["people"]["member_b"]["user_id"], world["a"]))


def _save_run(conn, world, name, org) -> int:
    """One match row and its detail, as this caller, the way a run from the page writes them."""
    funder = conn.execute("INSERT INTO funders (slug, name) VALUES (%s, 'F') RETURNING id",
                          (f"rls-f-{uuid4().hex[:8]}",)).fetchone()["id"]
    with conn.transaction():
        _as(conn, world["people"][name])
        match_id = conn.execute(
            """INSERT INTO funder_matches (run_id, org_id, funder_id, run_at, run_by, rubric_version, score, card)
               VALUES (%s, %s, %s, now(), %s, 'match-v1', 73, '{"reasons": []}') RETURNING id""",
            (uuid4(), org, funder, world["people"][name]["user_id"]),
        ).fetchone()["id"]
        conn.execute("INSERT INTO funder_match_details (match_id, detail) VALUES (%s, '{}')", (match_id,))
        conn.execute("RESET role")
    return match_id


@pytest.mark.parametrize("name, allowed", [("admin_a", True), ("steward_a", True), ("staff", True),
                                           ("member_a", False), ("member_b", False), ("nobody", False)])
def test_only_staff_stewards_and_admins_save_a_match_run(db, name, allowed):
    conn, world = db
    if allowed:
        assert _save_run(conn, world, name, world["a"])
    else:
        with pytest.raises(InsufficientPrivilege), conn.transaction(force_rollback=True):
            _save_run(conn, world, name, world["a"])


def test_a_run_cannot_be_saved_in_someone_elses_name(db):
    conn, world = db
    funder = conn.execute("INSERT INTO funders (slug, name) VALUES (%s, 'F') RETURNING id",
                          (f"rls-f-{uuid4().hex[:8]}",)).fetchone()["id"]
    with pytest.raises(InsufficientPrivilege), conn.transaction(force_rollback=True):
        _as(conn, world["people"]["admin_a"])
        conn.execute(
            """INSERT INTO funder_matches (run_id, org_id, funder_id, run_at, run_by, rubric_version, card)
               VALUES (%s, %s, %s, now(), %s, 'match-v1', '{}')""",
            (uuid4(), world["a"], funder, world["people"]["staff"]["user_id"]),
        )


@pytest.mark.parametrize("name, expected", [("member_a", 2), ("steward_a", 2), ("staff", 2),
                                            ("member_b", 0), ("nobody", 0)])
def test_saved_runs_reach_the_orgs_members_and_staff_and_a_rerun_keeps_both(db, name, expected):
    conn, world = db
    first = _save_run(conn, world, "admin_a", world["a"])
    _save_run(conn, world, "steward_a", world["a"])
    who = world["people"][name]
    assert _sees(conn, who, "SELECT DISTINCT run_id FROM funder_matches WHERE org_id = %s", (world["a"],)) == expected
    assert _sees(conn, who, "SELECT 1 FROM funder_match_details WHERE match_id = %s", (first,)) == min(expected, 1)


def test_a_saved_run_cannot_be_edited_or_deleted(db):
    conn, world = db
    match_id = _save_run(conn, world, "admin_a", world["a"])
    for sql in ["UPDATE funder_matches SET score = 100 WHERE id = %s", "DELETE FROM funder_matches WHERE id = %s"]:
        with pytest.raises(InsufficientPrivilege), conn.transaction(force_rollback=True):
            _as(conn, world["people"]["staff"])
            conn.execute(sql, (match_id,))

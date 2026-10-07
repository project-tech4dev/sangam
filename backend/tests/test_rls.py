"""Which rows each caller sees once RLS is on (0027), against the live compose Postgres.

Everything runs in one transaction that is rolled back, so the people and rows made here never land.
"""

import json
import os
from uuid import uuid4

import psycopg
import pytest
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
    for name, staff in [("member_a", False), ("steward_a", False), ("member_b", False),
                        ("nobody", False), ("staff", True)]:
        auth_id = uuid4()
        user_id = one(
            "INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, %s) RETURNING id",
            (f"{name}-{tag}@rls.test", auth_id, staff),
        )["id"]
        people[name] = {"user_id": user_id, "sub": str(auth_id)}
    for name, org, role in [("member_a", a, "member"), ("steward_a", a, "steward"), ("member_b", b, "member")]:
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

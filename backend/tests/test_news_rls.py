"""Who reads which news rows once 0044 is in (spec section 3, "Visibility is written, not computed on read")."""

from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from tests.test_rls import DSN, _as

pytestmark = pytest.mark.integration


@pytest.fixture
def db():
    try:
        conn = psycopg.connect(DSN, connect_timeout=3, row_factory=dict_row)
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable")
    if conn.execute("SELECT to_regclass('news_stories') AS t").fetchone()["t"] is None:
        pytest.skip("0044 not applied")
    with conn, conn.transaction(force_rollback=True):
        yield conn


def _world(conn):
    def one(sql, p=()):
        return conn.execute(sql, p).fetchone()

    tag = uuid4().hex[:8]
    org = one("INSERT INTO orgs (slug, name) VALUES (%s, 'N') RETURNING id", (f"news-{tag}",))["id"]
    staff = one("INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, true) RETURNING id, auth_user_id",
                (f"s-{tag}@t", uuid4()))
    member = one("INSERT INTO users (email, auth_user_id) VALUES (%s, %s) RETURNING id, auth_user_id",
                 (f"m-{tag}@t", uuid4()))
    ids = {}
    for vis in ("public", "listed", "hidden"):
        s = one("INSERT INTO news_stories (headline, topic) VALUES (%s, 'other') RETURNING id", (vis,))["id"]
        one("INSERT INTO news_story_entities (story_id, org_id, match, confidence, visibility) "
            "VALUES (%s, %s, 0.9, 0.95, %s) RETURNING id", (s, org, vis))
        ids[vis] = s
    ids["topic"] = one("INSERT INTO news_stories (headline, topic, visibility) VALUES ('t', 'fcra', 'listed') "
                       "RETURNING id")["id"]
    return ids, {"staff": {"sub": str(staff["auth_user_id"])}, "member": {"sub": str(member["auth_user_id"])}}


def _headlines(conn, who, ids):
    """Only this test's stories: other tests leave rows in the scratch database."""
    with conn.transaction(force_rollback=True):
        _as(conn, who)
        rows = conn.execute("SELECT headline FROM news_stories WHERE id = ANY(%s)", (list(ids.values()),))
        return sorted(r["headline"] for r in rows.fetchall())


def test_signed_out_sees_only_public_entity_stories(db):
    ids, _ = _world(db)
    assert _headlines(db, None, ids) == ["public"]


def test_signed_in_sees_listed_and_topic_stories_but_not_hidden(db):
    ids, who = _world(db)
    assert _headlines(db, who["member"], ids) == ["listed", "public", "t"]


def test_staff_sees_everything(db):
    ids, who = _world(db)
    assert _headlines(db, who["staff"], ids) == ["hidden", "listed", "public", "t"]


def test_scores_and_watermarks_are_staff_only(db):
    _, who = _world(db)
    for table in ("news_link_scores", "news_watch"):
        with db.transaction(force_rollback=True):
            _as(db, who["member"])
            assert db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
        with db.transaction(force_rollback=True):
            _as(db, None)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(f"SELECT 1 FROM {table}")

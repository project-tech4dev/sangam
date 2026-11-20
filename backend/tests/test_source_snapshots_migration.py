"""0058: source_snapshots and entity_research.snapshot_ids, staff-only like entity_research."""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def conn():
    try:
        with psycopg.connect(DSN, connect_timeout=3, row_factory=dict_row, autocommit=True) as connection:
            yield connection
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")


def test_the_table_has_its_columns(conn):
    rows = conn.execute(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'source_snapshots'"
    ).fetchall()
    columns = {r["column_name"]: r["is_nullable"] for r in rows}
    assert columns == {"id": "NO", "url": "NO", "kind": "YES", "text_hash": "NO", "archive_key": "YES",
                       "first_seen_at": "NO", "last_seen_at": "NO"}


def test_a_url_and_hash_is_one_row(conn):
    row = conn.execute(
        "SELECT 1 FROM pg_constraint WHERE conrelid = 'source_snapshots'::regclass AND contype = 'u' "
        "AND pg_get_constraintdef(oid) = 'UNIQUE (url, text_hash)'"
    ).fetchone()
    assert row is not None


def test_entity_research_has_snapshot_ids(conn):
    row = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'entity_research' AND column_name = 'snapshot_ids'"
    ).fetchone()
    assert row == {"data_type": "ARRAY"}


def test_staff_only_like_entity_research(conn):
    rows = conn.execute(
        "SELECT c.relname, c.relrowsecurity, has_table_privilege('authenticated', c.oid, 'SELECT') AS can, "
        "has_table_privilege('anon', c.oid, 'SELECT') AS anon_can, "
        "(SELECT qual FROM pg_policies p WHERE p.tablename = c.relname AND p.cmd = 'SELECT' LIMIT 1) AS qual "
        "FROM pg_class c WHERE c.relname IN ('source_snapshots', 'entity_research')"
    ).fetchall()
    by_name = {r["relname"]: r for r in rows}
    snapshots, research = by_name["source_snapshots"], by_name["entity_research"]
    assert snapshots["relrowsecurity"] and snapshots["can"] and not snapshots["anon_can"]
    assert snapshots["qual"] == research["qual"]

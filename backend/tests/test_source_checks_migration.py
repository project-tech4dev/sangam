"""0059, 0062 and 0063: source_checks, one row per source per check, and source_check_runs, one per run; staff-only."""

from __future__ import annotations

import pytest

from tests.test_source_snapshots_migration import conn  # noqa: F401 — the module's connection fixture

pytestmark = pytest.mark.integration


def test_the_table_has_its_columns(conn):  # noqa: F811
    rows = conn.execute(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'source_checks'"
    ).fetchall()
    assert {r["column_name"]: r["is_nullable"] for r in rows} == {
        "id": "NO", "run_id": "NO", "slug": "NO", "url": "NO", "checked_at": "NO", "baseline_snapshot_id": "YES",
        "new_snapshot_id": "YES", "status": "NO", "findings_intact": "NO", "findings_broken": "NO",
        "findings_unanchored": "NO", "judge": "YES", "detail": "YES", "removed_text": "NO", "added_text": "NO",
        "evidence": "YES"}


def test_a_status_outside_the_eight_is_refused(conn):  # noqa: F811
    row = conn.execute(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
        "WHERE conrelid = 'source_checks'::regclass AND contype = 'c'"
    ).fetchone()
    assert all(s in row["def"] for s in ("unchanged", "differs", "minor", "changed", "unverified", "dead", "new", "gap"))


def test_staff_only_like_source_snapshots(conn):  # noqa: F811
    rows = conn.execute(
        "SELECT c.relname, c.relrowsecurity, has_table_privilege('authenticated', c.oid, 'SELECT') AS can, "
        "has_table_privilege('anon', c.oid, 'SELECT') AS anon_can, "
        "(SELECT qual FROM pg_policies p WHERE p.tablename = c.relname AND p.cmd = 'SELECT' LIMIT 1) AS qual "
        "FROM pg_class c WHERE c.relname IN ('source_checks', 'source_snapshots')"
    ).fetchall()
    checks, snapshots = sorted(rows, key=lambda r: r["relname"])
    assert checks["relrowsecurity"] and checks["can"] and not checks["anon_can"]
    assert checks["qual"] == snapshots["qual"]


def test_runs_are_staff_only_too(conn):  # noqa: F811
    row = conn.execute(
        "SELECT c.relrowsecurity, has_table_privilege('authenticated', c.oid, 'SELECT') AS can, "
        "has_table_privilege('anon', c.oid, 'SELECT') AS anon_can FROM pg_class c WHERE c.relname = 'source_check_runs'"
    ).fetchone()
    assert row["relrowsecurity"] and row["can"] and not row["anon_can"]

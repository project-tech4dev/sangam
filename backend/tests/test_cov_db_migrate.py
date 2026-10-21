"""The migration runner against a fake connection: pending, applied, drift, status and a failing file."""

from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import quote

import psycopg
import pytest
from langgraph.checkpoint.postgres import PostgresSaver

from app.db import migrate
from app.db.checkpointer import CHECKPOINT_VERSION


class FakeConn:
    def __init__(self, applied: dict[str, str], fail_on: str | None = None):
        self.applied = dict(applied)
        self.fail_on = fail_on
        self.ran: list[str] = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.commits += 1

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=None):
        conn = self

        class Result:
            def fetchall(self_inner):
                return list(conn.applied.items())

        if sql.startswith("INSERT INTO schema_migrations"):
            self.applied[params[0]] = params[1]
        elif "schema_migrations" not in sql:
            if self.fail_on and self.fail_on in sql:
                raise RuntimeError("syntax error at or near BOOM")
            self.ran.append(sql)
        return Result()


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a ();")
    (tmp_path / "0002_b.sql").write_text("CREATE TABLE b (); BOOM")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    def _run(conn: FakeConn, *argv: str) -> tuple[int, str, str]:
        monkeypatch.setattr(migrate.sys, "argv", ["migrate", *argv])
        monkeypatch.setattr(migrate.psycopg, "connect", lambda url, autocommit: conn)
        monkeypatch.setattr(migrate, "migrate_checkpointer", lambda url, status_only: conn.ran.append(
            f"checkpointer status={status_only}"))
        code = migrate.main()
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def test_pending_files_are_applied_in_order(run):
    conn = FakeConn({})
    code, out, _ = run(conn)
    assert code == 0 and conn.ran == ["CREATE TABLE a ();", "CREATE TABLE b (); BOOM", "checkpointer status=False"]
    assert set(conn.applied) == {"0001_a", "0002_b"} and "2 migration(s) applied" in out


def test_nothing_pending_and_drift_is_reported(run):
    conn = FakeConn({"0001_a": migrate._checksum("CREATE TABLE a ();"), "0002_b": "stale"})
    code, out, _ = run(conn)
    assert code == 0 and conn.ran == ["checkpointer status=False"]
    assert "= 0001_a (applied earlier)" in out and "0002_b — DRIFT" in out and "up to date" in out


def test_status_lists_pending_without_running(run):
    conn = FakeConn({"0001_a": migrate._checksum("CREATE TABLE a ();")})
    code, out, _ = run(conn, "--status")
    assert code == 0 and conn.ran == ["checkpointer status=True"] and "+ 0002_b (pending)" in out and "1 migration(s) pending" in out
    assert "= 0001_a (applied )" in out


def test_a_failing_file_stops_the_run(run):
    conn = FakeConn({}, fail_on="BOOM")
    code, _, err = run(conn)
    assert code == 1 and "0002_b" not in conn.applied and "0001_a" in conn.applied
    assert "x 0002_b FAILED" in err and "no further migrations" in err
    assert "checkpointer status=False" not in conn.ran


class FakeSaver:
    """PostgresSaver.from_conn_string's context manager, holding the checkpoint version it reports."""

    def __init__(self, at: int | None):
        self.at, self.set_up = at, False
        saver = self

        class Conn:
            def execute(self, sql):
                table = "checkpoint_migrations" if saver.at is not None else None
                return SimpleNamespace(fetchone=lambda: {"t": table, "v": saver.at})

        self.conn = Conn()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def setup(self):
        self.set_up = True


@pytest.mark.parametrize(("at", "shown"), [(None, "v- of"), (2, "v2 of"), (CHECKPOINT_VERSION, "up to date")])
def test_checkpointer_status_reads_without_migrating(monkeypatch, capsys, at, shown):
    saver = FakeSaver(at)
    monkeypatch.setattr(PostgresSaver, "from_conn_string", lambda url: saver)
    migrate.migrate_checkpointer("postgresql://fake", status_only=True)
    assert not saver.set_up and shown in capsys.readouterr().out


def test_checkpointer_migrates_after_the_sql_files(monkeypatch, capsys):
    saver = FakeSaver(None)
    monkeypatch.setattr(PostgresSaver, "from_conn_string", lambda url: saver)
    migrate.migrate_checkpointer("postgresql://fake", status_only=False)
    assert saver.set_up and f"checkpointer at v{CHECKPOINT_VERSION}" in capsys.readouterr().out


def test_no_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert migrate.main() == 1 and "DATABASE_URL is not set" in capsys.readouterr().err


def test_no_migrations_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path / "missing")
    assert migrate.main() == 1 and "no migrations directory" in capsys.readouterr().err


DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")
SCHEMA = "cov_migrate_tmp"


@pytest.mark.integration
def test_the_runner_against_postgres_in_a_throwaway_schema(tmp_path, monkeypatch, capsys):
    try:
        admin = psycopg.connect(DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    with admin:
        admin.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        admin.execute(f"CREATE SCHEMA {SCHEMA}")
        try:
            (tmp_path / "0001_t.sql").write_text("CREATE TABLE t (id int);")
            (tmp_path / "0002_u.sql").write_text("INSERT INTO t VALUES (1);")
            monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
            monkeypatch.setattr(migrate.sys, "argv", ["migrate"])
            sep = "&" if "?" in DSN else "?"
            monkeypatch.setenv("DATABASE_URL", f"{DSN}{sep}options={quote(f'-csearch_path={SCHEMA}')}")
            assert migrate.main() == 0
            assert migrate.main() == 0
            assert "up to date" in capsys.readouterr().out
            rows = admin.execute(f"SELECT version FROM {SCHEMA}.schema_migrations ORDER BY 1").fetchall()
            assert [r[0] for r in rows] == ["0001_t", "0002_u"]
            assert admin.execute(f"SELECT count(*) FROM {SCHEMA}.t").fetchone()[0] == 1
            at = admin.execute(f"SELECT max(v) FROM {SCHEMA}.checkpoint_migrations").fetchone()[0]
            assert at == CHECKPOINT_VERSION
        finally:
            admin.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")

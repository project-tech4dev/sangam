"""The pool's written-down limits, the REST statement timeout, the checkpointer boot check and /health's counts."""

from __future__ import annotations

import os

import httpx
import psycopg
import pytest
from psycopg.errors import QueryCanceled
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings
from app.db import checkpointer
from app.db import pool as db_pool
from app.db.checkpointer import CHECKPOINT_VERSION, make_pool, open_checkpointer
from app.db.pool import CallerPool
from app.main import create_app


def test_the_pool_states_its_timeouts_and_checks_connections():
    settings = get_settings()
    pool = make_pool("postgresql://x/y")
    assert pool.timeout == settings.db_pool_timeout_s
    assert pool._check == AsyncConnectionPool.check_connection
    assert pool.max_idle == 300
    assert pool.kwargs["connect_timeout"] == settings.db_connect_timeout_s


def test_the_cli_pools_get_the_same_limits():
    pool = make_pool("postgresql://x/y", max_size=2)
    assert pool.max_size == 2 and pool.timeout == get_settings().db_pool_timeout_s


class FakeConn:
    def __init__(self):
        self.ran: list[tuple[str, tuple]] = []

    async def execute(self, sql, params=()):
        self.ran.append((sql, params))


class FakeOwner:
    """The owner pool: hands out one fake connection whose transaction does nothing."""

    def __init__(self):
        self.conn = FakeConn()
        conn = self.conn

        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        conn.transaction = lambda: _Tx()

    def connection(self):
        conn = self.conn

        class _Cm:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Cm()


async def test_rest_sets_role_claims_and_timeout_in_one_statement():
    owner = FakeOwner()
    async with CallerPool(owner, role="authenticated", claims='{"sub": "x"}', timeout_ms=1500).connection():
        pass
    [(sql, params)] = owner.conn.ran
    assert "statement_timeout" in sql and params == ("authenticated", '{"sub": "x"}', "1500")


async def test_the_timeout_defaults_to_the_setting():
    owner = FakeOwner()
    async with CallerPool(owner, role="anon", claims="").connection():
        pass
    assert owner.conn.ran[0][1][2] == str(get_settings().db_statement_timeout_ms)


async def test_ask_keeps_its_own_lower_timeout():
    # The executor sets its timeout, then set_caller; set_caller must not raise it back to REST's.
    conn = FakeConn()
    await db_pool.set_caller(conn, "anon", "")
    assert "statement_timeout" not in conn.ran[0][0]


@pytest.mark.parametrize(
    ("version", "message"),
    [(None, "no checkpoint tables"), (CHECKPOINT_VERSION - 1, f"v{CHECKPOINT_VERSION - 1}")],
)
async def test_boot_refuses_a_checkpointer_schema_make_migrate_has_not_set(monkeypatch, version, message):
    async def at(conn):
        return version

    monkeypatch.setattr(checkpointer, "checkpoint_version", at)
    with pytest.raises(RuntimeError, match=f"{message}.*run make migrate"):
        async with open_checkpointer(FakeOwner()):
            pass


async def test_boot_opens_the_saver_without_ddl(monkeypatch):
    async def at(conn):
        return CHECKPOINT_VERSION

    monkeypatch.setattr(checkpointer, "checkpoint_version", at)
    owner = FakeOwner()
    async with open_checkpointer(owner) as saver:
        assert saver.conn is owner
    assert owner.conn.ran == []


async def _health() -> dict:
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return (await client.get("/health")).json()


async def test_health_without_a_pool_says_ok_only(monkeypatch):
    monkeypatch.setattr(db_pool, "pool", None)
    assert await _health() == {"status": "ok"}


async def test_health_shows_pool_counts(monkeypatch):
    class Stats:
        def get_stats(self):
            return {"pool_max": 10, "pool_size": 3, "pool_available": 2, "requests_waiting": 1, "dsn": "secret"}

    monkeypatch.setattr(db_pool, "pool", Stats())
    pool = (await _health())["pool"]
    assert pool["requests_waiting"] == 1 and pool["connections_errors"] == 0 and "dsn" not in pool


DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")


@pytest.fixture
async def real_pool():
    try:
        await (await psycopg.AsyncConnection.connect(DSN, connect_timeout=3)).close()
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    pool = AsyncConnectionPool(
        DSN, min_size=1, max_size=1, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    yield pool
    await pool.close()


@pytest.mark.integration
async def test_a_rest_query_past_the_timeout_is_cancelled_and_does_not_stick(real_pool):
    with pytest.raises(QueryCanceled):
        async with CallerPool(real_pool, role="anon", claims="", timeout_ms=100).connection() as conn:
            await conn.execute("SELECT pg_sleep(1)")
    async with real_pool.connection() as conn:
        row = await (await conn.execute("SHOW statement_timeout")).fetchone()
    assert row["statement_timeout"] != "100ms"


@pytest.mark.integration
async def test_a_migrated_database_is_at_this_langgraphs_version(real_pool):
    async with real_pool.connection() as conn:
        assert await checkpointer.checkpoint_version(conn) == CHECKPOINT_VERSION

"""The server-side guards, proved independently against a real Postgres."""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row

from app.agent.tools.sql import catalog as cat
from app.agent.tools.sql.executor import MAX_CONCURRENT_QUERIES, PsycopgExecutor
from app.agent.tools.sql.validator import validate

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def conn():
    """autocommit=True to match the app's pool exactly."""
    try:
        with psycopg.connect(
            DSN, connect_timeout=3, row_factory=dict_row, autocommit=True
        ) as connection:
            yield connection
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")




class TestCatalogMatchesReality:
    """The gate that fails loudly when a migration changes the schema."""

    def test_no_drift(self, conn):
        rows = conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        ).fetchall()
        live: dict[str, set[str]] = {}
        for row in rows:
            live.setdefault(row["table_name"], set()).add(row["column_name"])

        problems = []
        for name, table in cat.CATALOG.items():
            if name not in live:
                problems.append(f"{name} is catalogued but missing from the database")
                continue
            missing = sorted({c.name for c in table.columns} - live[name])
            if missing:
                problems.append(f"{name}: catalogued columns not in the database: {missing}")
        assert not problems, problems

    def test_every_live_table_is_either_catalogued_or_knowingly_excluded(self, conn):
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ).fetchall()
        live = {r["table_name"] for r in rows}
        assert cat.undeclared_tables(live) == [], (
            "a new table exists that nobody has decided about; add it to the catalog "
            "or to KNOWN_EXCLUDED"
        )


class TestReadOnlyTransaction:
    """Layer 1, with the validator bypassed entirely."""

    def test_a_write_is_refused_even_though_the_connection_could_do_it(self, conn):
        with conn.transaction(force_rollback=True):
            conn.execute("SET TRANSACTION READ ONLY")
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                conn.execute("INSERT INTO orgs (slug, name) VALUES ('x', 'x')")

    def test_statement_timeout_fires(self, conn):
        """The row limit cannot bound this: a cartesian join reads many rows to
        return few."""
        with conn.transaction(force_rollback=True):
            conn.execute("SET LOCAL statement_timeout = 250")
            with pytest.raises(psycopg.errors.QueryCanceled):
                conn.execute(
                    "SELECT count(*) FROM generate_series(1, 200000) a, "
                    "generate_series(1, 200000) b"
                ).fetchall()



class TestNothingLeaksOntoThePool:
    """This pool is shared with the LangGraph checkpointer, which WRITES on every
    graph step. A guard that outlives its transaction would break chat."""

    def test_read_only_reverts_at_commit(self, conn):
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                conn.execute("INSERT INTO orgs (slug, name) VALUES ('x', 'x')")

        # the same pooled connection must still be writable for the checkpointer
        with conn.transaction(force_rollback=True):
            conn.execute("INSERT INTO orgs (slug, name) VALUES ('leak-probe', 'leak probe')")

    def test_statement_timeout_does_not_persist(self, conn):
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout = 100")
        after = conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"]
        assert after in ("0", "0ms"), f"timeout leaked onto the pooled connection: {after}"


class TestWireProtocol:
    def test_multi_statement_reaches_the_server_on_the_simple_protocol(self, conn):
        """Why prepare=True is not optional: without it this executes."""
        with conn.transaction(force_rollback=True):
            conn.execute("SELECT 1; SELECT 2", prepare=False)

    def test_and_is_refused_on_the_extended_protocol(self, conn):
        with conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.SyntaxError):
            conn.execute("SELECT 1; SELECT 2", prepare=True)

    def test_percent_literals_survive_with_no_params(self, conn):
        """params=None means psycopg does not scan for %, so ILIKE '%x%' is intact."""
        rows = conn.execute(
            validate("SELECT id, name FROM orgs WHERE name ILIKE '%a%'").sql, None, prepare=True
        ).fetchall()
        assert rows


def test_executor_concurrency_is_capped_below_the_pool_size():
    """pool max_size=5, shared with the checkpointer."""
    assert MAX_CONCURRENT_QUERIES < 5
    PsycopgExecutor(timeout_ms=5000)

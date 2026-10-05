"""The server-side guards, proved independently against a real Postgres."""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row

from app.agent.tools.sql import catalog as cat
from app.agent.tools.sql.executor import PsycopgExecutor, max_concurrent_queries
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
    """Whatever the pool is sized to, the gate stays under it — the checkpointer
    writes through the same pool on every graph step, and a gate set at the pool
    size starves it."""
    from app.core.config import get_settings

    assert 2 <= max_concurrent_queries() < get_settings().db_pool_max_size
    PsycopgExecutor(timeout_ms=5000)


class TestGeographyIsParentedCorrectly:
    """The defect the catalog used to carry, proved gone against real rows."""

    def test_no_district_hangs_off_the_wrong_state(self, conn):
        rows = conn.execute(
            """
            SELECT d.name AS district, s.name AS state
            FROM locations d JOIN locations s ON s.id = d.parent_id
            WHERE d.kind = 'district'
            """
        ).fetchall()
        if not rows:
            pytest.skip("no districts seeded")
        placed = {r["district"]: r["state"] for r in rows}
        # The three the catalog defect used to name, from Darpan's own
        # state_of_registration rather than from the seed's assumption.
        for district, state in (("DIMAPUR", "Nagaland"), ("BISHNUPUR", "Manipur"),
                                ("TAMENGLONG", "Manipur")):
            if district in placed:
                assert placed[district] == state

    def test_every_district_has_a_state_for_a_parent(self, conn):
        orphans = conn.execute(
            """
            SELECT d.name FROM locations d
            LEFT JOIN locations s ON s.id = d.parent_id AND s.kind = 'state'
            WHERE d.kind = 'district' AND s.id IS NULL
            """
        ).fetchall()
        assert orphans == [], f"districts with no state: {[o['name'] for o in orphans]}"


def test_the_pool_is_sized_by_the_setting_not_a_constant():
    """`max_size=5` in code and "about six at once" in the prompt were the same
    number written twice. Research fan-out is bounded by connections, so the
    two have to move together."""
    from app.core.config import Settings
    from app.db.checkpointer import make_pool

    pool = make_pool("postgresql://x/y")
    assert pool.max_size == Settings().db_pool_max_size
    # The SHIPPED defaults, not the running config: someone may deliberately
    # run more researchers than connections and let the waves queue. That is
    # their call to make in .env, not a broken build.
    assert (
        Settings.model_fields["max_parallel_research"].default
        <= Settings.model_fields["db_pool_max_size"].default
    )


def test_a_one_org_shortlist_fits_under_the_row_cap(conn):
    """The funder shortlist is one row per funder; past the cap it would truncate silently."""
    from app.core.config import get_settings

    cap = get_settings().sql_max_rows  # what db_query passes to validate(), not the validator's default
    funders = conn.execute("SELECT count(*) AS n FROM funders").fetchone()["n"]
    assert funders < cap, (
        f"{funders} funders reach db_query's {cap}-row cap — "
        "the shortlist procedure needs paging before it can list them all"
    )


class TestTaxonomyCrosswalk:
    """0022 on a seeded database: the shortlist's thematic join reads tags.meta->>'maps_to'."""

    def test_every_sector_tag_has_decided_a_clause(self, conn):
        undecided = conn.execute(
            "SELECT slug FROM tags WHERE kind = 'sector' AND NOT meta ? 'maps_to' ORDER BY slug"
        ).fetchall()
        assert not undecided, f"sector tags with no maps_to key: {[r['slug'] for r in undecided]}"

    def test_every_clause_names_a_csr_sector_tag(self, conn):
        # Assumes a seeded database: taxonomy_seed creates the csr_sector rows after migrate runs.
        dangling = conn.execute(
            "SELECT s.slug, s.meta->>'maps_to' AS maps_to FROM tags s "
            "WHERE s.kind = 'sector' AND s.meta->>'maps_to' IS NOT NULL AND NOT EXISTS ("
            "  SELECT 1 FROM tags c WHERE c.kind = 'csr_sector' AND c.slug = s.meta->>'maps_to')"
        ).fetchall()
        assert not dangling, f"maps_to names no csr_sector tag: {dangling}"

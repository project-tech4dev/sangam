import json
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agent.tools.sql.executor import PsycopgExecutor
from app.agent.tools.sql.validator import validate
from app.db import pool as db_pool
from app.db.pool import agent_caller
from tests.conftest import DSN

pytestmark = pytest.mark.integration

MARKER = f"rls-{uuid4()}"


def as_user(auth_id) -> tuple[str, str]:
    return "authenticated", json.dumps({"sub": str(auth_id), "role": "authenticated"})


@pytest.fixture
async def owner_pool(monkeypatch):
    try:
        await (await psycopg.AsyncConnection.connect(DSN, connect_timeout=3)).close()
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    pool = AsyncConnectionPool(
        DSN, min_size=1, max_size=4, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    monkeypatch.setattr(db_pool, "pool", pool)
    yield pool
    await pool.close()


@pytest.fixture
async def planted(owner_pool):
    """Org B's private document, a staff-only funder line, and a member of Org A."""
    member_auth = uuid4()
    try:
        async with owner_pool.connection() as conn:
            org_a, org_b = [r["id"] for r in await (await conn.execute(
                "SELECT id FROM orgs ORDER BY id LIMIT 2")).fetchall()]
            funder = (await (await conn.execute("SELECT id FROM funders ORDER BY id LIMIT 1")).fetchone())["id"]
            await conn.execute(
                "INSERT INTO documents (org_id, title, doc_type, content_md, is_public) VALUES "
                "(%s, 'A private', 'vault', %s, false), (%s, 'B private', 'vault', %s, false)",
                (org_a, f"{MARKER} A", org_b, f"{MARKER} B"),
            )
            await conn.execute(
                "INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, notes, is_public) "
                "VALUES (%s, 'partner', 'FY2024-25', 'Test partner', %s, false)",
                (funder, MARKER),
            )
            user = (await (await conn.execute(
                "INSERT INTO users (email, auth_user_id) VALUES (%s, %s) RETURNING id",
                (f"{MARKER}@test.local", member_auth),
            )).fetchone())["id"]
            await conn.execute(
                "INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, 'member')", (user, org_a))
        yield member_auth
    finally:
        async with owner_pool.connection() as conn:
            await conn.execute("DELETE FROM users WHERE email = %s", (f"{MARKER}@test.local",))
            await conn.execute("DELETE FROM funder_activity WHERE notes = %s", (MARKER,))
            await conn.execute("DELETE FROM documents WHERE content_md LIKE %s", (f"{MARKER}%",))


async def query(sql: str) -> list[dict]:
    return await PsycopgExecutor(timeout_ms=5_000).run(validate(sql))


DOCS = f"SELECT title FROM documents WHERE content_md LIKE '{MARKER}%' ORDER BY title"
ACTIVITY = f"SELECT id FROM funder_activity WHERE notes = '{MARKER}'"


async def test_a_member_of_org_a_reads_its_own_private_document_and_not_org_bs(planted):
    agent_caller.set(as_user(planted))
    assert [r["title"] for r in await query(DOCS)] == ["A private"]
    assert await query(ACTIVITY) == []


async def test_a_user_with_no_organisation_reads_no_private_row(planted):
    agent_caller.set(as_user(uuid4()))
    assert await query(DOCS) == []
    assert await query(ACTIVITY) == []


async def test_with_no_caller_the_agent_reads_as_anon(planted):
    agent_caller.set(None)
    assert await query(DOCS) == []


async def test_the_connection_returns_to_the_pool_as_the_owner(planted, owner_pool):
    agent_caller.set(as_user(uuid4()))
    await query(DOCS)
    async with owner_pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT current_user = session_user AS owner, current_setting('request.jwt.claims', true) AS claims"
        )).fetchone()
    assert row["owner"] and not row["claims"]


async def test_every_catalog_column_is_readable_by_a_signed_in_caller(owner_pool):
    from app.agent.tools.sql.catalog import CATALOG

    pairs = [(t, c.name) for t, table in CATALOG.items() for c in table.columns]
    async with owner_pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT t, c FROM unnest(%s::text[], %s::text[]) AS p(t, c) "
            "WHERE NOT has_column_privilege('authenticated', t, c, 'SELECT')",
            ([t for t, _ in pairs], [c for _, c in pairs]),
        )).fetchall()
    assert rows == [], "the chat runs as the caller, so a column it cannot SELECT breaks `SELECT *`"

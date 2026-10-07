"""The matching profiles against the compose Postgres: the fixed queries run, and KABIL reads as recorded."""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agent.tools.matching_tools import compare
from app.repositories import matching

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

pytestmark = pytest.mark.integration


@pytest.fixture
async def pool():
    try:
        psycopg.connect(DSN, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    async with AsyncConnectionPool(
        DSN, kwargs={"row_factory": dict_row, "autocommit": True}, open=False, min_size=1, max_size=2
    ) as p:
        yield p


async def _kabil_id(pool) -> int:
    async with pool.connection() as conn:
        return (await (await conn.execute("SELECT id FROM orgs WHERE slug = 'kabil'")).fetchone())["id"]


async def test_kabil_against_axis_bank_foundation(pool):
    org_id = await _kabil_id(pool)
    async with pool.connection() as conn:
        axis = (await (await conn.execute(
            "SELECT id FROM funders WHERE name = 'Axis Bank Foundation'")).fetchone())["id"]
    org, funders, places = await matching.load(pool, org_id, [axis])
    out = compare(org, funders, places, shortlist=False)
    area = next(c for c in out["assessed"][0]["checks"] if c["code"] == "area")
    assert (area["outcome"], area["level"]) == ("met", "district")
    assert "Udalguri" in area["note"]
    reg_12a = next(c for c in out["readiness"] if c["code"] == "reg_12a")
    assert reg_12a["cites"] == [f"[org:{org_id}]"]


async def test_a_shortlist_reads_every_funder_in_one_call(pool):
    org, funders, places = await matching.load(pool, await _kabil_id(pool), None)
    out = compare(org, funders, places, shortlist=True)
    counted = len(out["assessed"]) + out["not_assessed"]["nothing_in_common_recorded"] + len(
        out["not_assessed"]["nothing_recorded"])
    assert counted == out["funders_considered"] > 0


async def test_the_read_is_read_only(pool):
    async with pool.connection() as conn, conn.transaction():
        await matching._read_only(conn, 1000)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            await conn.execute("CREATE TEMP TABLE x (i int)")

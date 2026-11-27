"""The pool's claim SQL against a migrated Postgres, inside a transaction that is rolled back."""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row

from app.ingest.pool import queue

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")
CAT = "test_category"

pytestmark = pytest.mark.integration


class Rollback(Exception):
    pass


async def _run(check) -> None:
    try:
        conn = await psycopg.AsyncConnection.connect(DSN, connect_timeout=3, row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("no Postgres on :5433")
    async with conn:
        try:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO funder_ingest_settings (category, enabled, max_parallel, min_csr_spend_cr, daily_cap)"
                    " VALUES (%s, true, 2, 10, 3)", (CAT,))
                for slug, rank, spend, prio in [("a", 1, 50, None), ("b", 2, 5, None), ("c", 3, 20, None),
                                                ("d", 4, 30, 1), ("e", 5, 40, None)]:
                    await conn.execute(
                        "INSERT INTO funder_pool (pool_funder_id, category, name, rank_in_category, "
                        "csr_spend_3y_avg_cr, priority_override) VALUES (%s, %s, %s, %s, %s, %s)",
                        (f"{slug}-{CAT}", CAT, slug.upper(), rank, spend, prio))
                await check(conn)
                raise Rollback
        except Rollback:
            pass


async def test_claims_priority_first_then_rank_above_the_floor_within_max_parallel():
    async def check(conn):
        claimed = await queue.claim(conn, CAT, "w1")
        assert {r["name"] for r in claimed} == {"D", "A"}  # D is overridden up over C; B is under the floor
        assert all(r["ingest_status"] == "running" and r["attempts"] == 1 for r in claimed)
        assert await queue.claim(conn, CAT, "w1") == []  # both slots are taken

    await _run(check)


async def test_the_daily_cap_counts_today_s_claims():
    async def check(conn):
        first = await queue.claim(conn, CAT, "w1")
        for row in first:
            await queue.start_run(conn, row)
            await queue.finish(conn, row, "done")
        assert [r["name"] for r in await queue.claim(conn, CAT, "w1")] == ["C"]  # 3 a day: one left

    await _run(check)


async def test_a_stale_lock_returns_to_pending_and_its_run_fails():
    async def check(conn):
        row = (await queue.claim(conn, CAT, "w1"))[0]
        run_id = await queue.start_run(conn, row)
        await conn.execute("UPDATE funder_pool SET locked_at = now() - interval '2 hours' WHERE id = %s",
                           (row["id"],))
        await conn.execute(queue.RECOVER, {"category": CAT})
        back = await (await conn.execute("SELECT ingest_status, last_error FROM funder_pool WHERE id = %s",
                                         (row["id"],))).fetchone()
        assert back["ingest_status"] == "pending" and "lock expired" in back["last_error"]
        run = await (await conn.execute("SELECT status FROM ingest_runs WHERE id = %s", (run_id,))).fetchone()
        assert run["status"] == "failed"
        again = (await queue.claim(conn, CAT, "w2"))[0]
        assert again["id"] == row["id"]
        await queue.finish(conn, row, "done")  # the first claim ends late: it must not touch w2's
        now = await (await conn.execute("SELECT ingest_status, locked_by FROM funder_pool WHERE id = %s",
                                        (row["id"],))).fetchone()
        assert now["ingest_status"] == "running" and now["locked_by"] == "w2"

    await _run(check)


async def test_a_shutdown_gives_the_attempt_back():
    async def check(conn):
        row = (await queue.claim(conn, CAT, "w1"))[0]
        await queue.start_run(conn, row)
        await queue.finish(conn, row, "pending", error="stopped", refund=True)
        back = await (await conn.execute("SELECT attempts FROM funder_pool WHERE id = %s", (row["id"],))).fetchone()
        assert back["attempts"] == 0

    await _run(check)


async def test_a_failure_retries_until_max_attempts():
    async def check(conn):
        row = (await queue.claim(conn, CAT, "w1"))[0]
        await queue.start_run(conn, row)
        assert await queue.fail(conn, row, "boom") == "pending"
        assert await queue.fail(conn, {**row, "attempts": 3}, "boom") == "failed"

    await _run(check)

"""claim_thread's question count against the compose Postgres: the limit, the race, and whose turns count."""

from __future__ import annotations

import asyncio
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app.repositories.threads import asked, claim_thread
from tests.conftest import DSN

pytestmark = pytest.mark.integration


@pytest.fixture
async def visitor():
    """A pool like the app's (autocommit), and a user removed with their threads afterwards."""
    try:
        pool = AsyncConnectionPool(DSN, open=False, min_size=1, max_size=4,
                                   kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 3})
        await pool.open(wait=True, timeout=5)
    except (psycopg.OperationalError, PoolTimeout):
        pytest.skip("compose Postgres not reachable on localhost:5433")
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "INSERT INTO users (email) VALUES (%s) RETURNING id", (f"free-{uuid.uuid4()}@test.local",)
        )).fetchone()
    try:
        yield pool, row["id"]
    finally:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM threads WHERE user_id = %s", (row["id"],))
            await conn.execute("DELETE FROM users WHERE id = %s", (row["id"],))
        await pool.close()


async def test_each_turn_is_a_question_and_the_one_past_the_limit_is_refused(visitor):
    pool, user = visitor
    for i in range(3):
        assert await claim_thread(pool, thread_id=f"t-{user}-{i % 2}", user_id=user, limit=3) == user
    assert await asked(pool, user_id=user) == 3
    assert await claim_thread(pool, thread_id=f"t-{user}-new", user_id=user, limit=3) is None
    assert await asked(pool, user_id=user) == 3


async def test_two_tabs_at_the_last_question_get_one_between_them(visitor):
    pool, user = visitor
    await claim_thread(pool, thread_id=f"t-{user}-a", user_id=user, limit=2)
    owners = await asyncio.gather(*(
        claim_thread(pool, thread_id=f"t-{user}-{tab}", user_id=user, limit=2) for tab in ("b", "c")
    ))
    assert sorted(o is None for o in owners) == [False, True]
    assert await asked(pool, user_id=user) == 2


async def test_any_thread_id_counts_but_someone_elses_thread_does_not(visitor):
    pool, user = visitor
    await claim_thread(pool, thread_id=f"import-{user}", user_id=user)
    async with pool.connection() as conn:
        other = (await (await conn.execute(
            "INSERT INTO users (email) VALUES (%s) RETURNING id", (f"other-{uuid.uuid4()}@test.local",)
        )).fetchone())["id"]
    try:
        await claim_thread(pool, thread_id=f"t-{other}", user_id=other)
        assert await claim_thread(pool, thread_id=f"t-{other}", user_id=user) == other
        assert await asked(pool, user_id=user) == 1  # an import- id posted to /agent is still a question
        assert await asked(pool, user_id=other) == 1
    finally:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM threads WHERE user_id = %s", (other,))
            await conn.execute("DELETE FROM users WHERE id = %s", (other,))

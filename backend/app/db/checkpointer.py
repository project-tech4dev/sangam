"""Pooled Postgres LangGraph checkpointer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def make_pool(database_url: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )


@asynccontextmanager
async def open_checkpointer(pool: AsyncConnectionPool) -> AsyncIterator[AsyncPostgresSaver]:
    saver = AsyncPostgresSaver(pool)
    await saver.setup()  # idempotent DDL; acceptable at boot for local dev
    yield saver

"""Pooled Postgres LangGraph checkpointer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings


def make_pool(database_url: str, max_size: int | None = None) -> AsyncConnectionPool:
    """The one pool: REST, the agent tools and the checkpointer all share it.

    `max_size` defaults to the setting rather than a constant, because how many
    organisations may be researched at once is bounded by how many connections
    this process may hold.
    """
    return AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=max_size if max_size is not None else get_settings().db_pool_max_size,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )


@asynccontextmanager
async def open_checkpointer(pool: AsyncConnectionPool) -> AsyncIterator[AsyncPostgresSaver]:
    saver = AsyncPostgresSaver(pool)
    await saver.setup()  # idempotent DDL; acceptable at boot for local dev
    yield saver

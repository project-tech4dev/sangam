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
    settings = get_settings()
    return AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=max_size if max_size is not None else settings.db_pool_max_size,
        open=False,
        # A request that waits longer than this for a connection is already lost; say so instead of hanging.
        timeout=settings.db_pool_timeout_s,
        # A thawed Vercel instance may hold sockets the pooler closed; one round trip beats a failed request.
        check=AsyncConnectionPool.check_connection,
        max_idle=300,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "connect_timeout": settings.db_connect_timeout_s,
        },
    )


# The last checkpointer migration this langgraph version expects; `make migrate` applies them.
CHECKPOINT_VERSION = len(AsyncPostgresSaver.MIGRATIONS) - 1


async def checkpoint_version(conn) -> int | None:
    """The checkpointer migration the database is at, or None when it was never migrated."""
    exists = await (await conn.execute("SELECT to_regclass('checkpoint_migrations') AS t")).fetchone()
    if exists["t"] is None:
        return None
    row = await (await conn.execute("SELECT max(v) AS v FROM checkpoint_migrations")).fetchone()
    return row["v"]


@asynccontextmanager
async def open_checkpointer(pool: AsyncConnectionPool) -> AsyncIterator[AsyncPostgresSaver]:
    """The saver, once the database is at this langgraph's schema. No DDL here: concurrent cold starts would race."""
    async with pool.connection() as conn:
        version = await checkpoint_version(conn)
    if version != CHECKPOINT_VERSION:
        found = "no checkpoint tables" if version is None else f"checkpoint schema v{version}"
        raise RuntimeError(f"{found}, this langgraph expects v{CHECKPOINT_VERSION}: run make migrate")
    yield AsyncPostgresSaver(pool)

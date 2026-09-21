"""Pooled Postgres LangGraph checkpointer.

Unlike AsyncPostgresSaver.from_conn_string (a single connection that serializes
concurrent streams), this opens an AsyncConnectionPool. The pool kwargs are the
documented requirements for the saver: autocommit so setup() DDL commits,
prepare_threshold=0 to stay compatible with transaction poolers, and dict_row
because the saver reads rows by column name.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

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

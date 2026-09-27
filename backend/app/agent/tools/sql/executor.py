"""Run a validated query under every server-side guard we have."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from app.agent.tools.sql.validator import ValidatedQuery
from app.db.pool import get_pool
from app.integrations.tracing import traced_fetch

logger = logging.getLogger(__name__)


# The pool is max_size=5 and shared with the checkpointer, which writes on every
# graph step, so tool concurrency is capped well below the pool size.
MAX_CONCURRENT_QUERIES = 2


class Executor(Protocol):
    async def run(self, query: ValidatedQuery) -> list[dict[str, Any]]: ...


class PsycopgExecutor:
    """Executes against the app's shared psycopg pool."""

    def __init__(self, *, timeout_ms: int = 5_000) -> None:
        self._timeout_ms = int(timeout_ms)
        if self._timeout_ms <= 0:
            raise ValueError(f"timeout_ms must be positive, got {timeout_ms}")
        self._gate: asyncio.Semaphore | None = None

    def _semaphore(self) -> asyncio.Semaphore:
        """Created on first use, not at import: a Semaphore built before the
        event loop exists is fragile across loop restarts (notably in tests)."""
        if self._gate is None:
            self._gate = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)
        return self._gate

    async def run(self, query: ValidatedQuery) -> list[dict[str, Any]]:
        pool = get_pool()
        # conn.transaction() is what emits BEGIN, because the pool runs with autocommit=True. Without it
        # every SET in _harden would be a no-op or, worse, would persist on the connection after it returns.
        async with (
            self._semaphore(),
            pool.connection() as conn,
            conn.transaction(),
        ):
            await self._harden(conn)
            return await traced_fetch(
                conn,
                query.sql,
                None,
                name="agent-sql",
                # Forces the extended protocol; the server then refuses
                # multi-command statements itself.
                prepare=True,
            )

    async def _harden(self, conn: Any) -> None:
        # Must be the first statement of the transaction: Postgres refuses
        # SET TRANSACTION after a query has run in it.
        await conn.execute("SET TRANSACTION READ ONLY")
        await conn.execute(f"SET LOCAL statement_timeout = {self._timeout_ms}")
        await conn.execute("SET LOCAL lock_timeout = 1000")
        await conn.execute("SET LOCAL idle_in_transaction_session_timeout = 10000")


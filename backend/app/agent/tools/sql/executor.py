"""Run a validated query under every server-side guard we have.

The guards are layered because each covers what the others miss:

  1. `SET TRANSACTION READ ONLY` — blocks writes even if the validator has a hole.
  2. `SET LOCAL statement_timeout` — bounds a query the row limit cannot
     (a cartesian join returns few rows after reading many).
  3. `SET LOCAL ROLE` — drops superuser, so pg_read_file and the checkpoint
     tables become unreachable rather than merely un-asked-for.
  4. `prepare=True` — makes the SERVER refuse multiple commands in one
     statement. With the simple protocol `SELECT 1; RESET ROLE` executes, and
     RESET ROLE would undo guard 3.

All of it is transaction-scoped. That matters more than it looks: this pool is
shared with the LangGraph checkpointer, which WRITES on every graph step, so
anything leaking onto a pooled connection would break checkpointing for the
whole app. `SET LOCAL` inside an explicit transaction is what keeps it contained
— the pool has `autocommit=True` and no `configure`/`reset` hook, so without the
explicit transaction none of these statements would mean anything.

The Executor Protocol is the portability seam the brief asked SQLAlchemy for: a
second database means one more implementation here, and the validator does not
change.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from psycopg import sql as pgsql

from app.agent.tools.sql.validator import ValidatedQuery
from app.db.pool import get_pool
from app.integrations.tracing import traced_fetch

logger = logging.getLogger(__name__)

# Postgres: undefined_object. What SET LOCAL ROLE raises when the reader role
# does not exist because migration 0001 has not been applied.
UNDEFINED_OBJECT = "42704"

# The pool is max_size=5 and shared with the checkpointer, which writes on every
# graph step. Two concurrent agent runs each holding a connection for the full
# statement timeout would starve it, so tool concurrency is capped well below
# the pool size. This is the most likely operational failure of this feature.
MAX_CONCURRENT_QUERIES = 2


class ReaderRoleMissing(RuntimeError):
    """The reader role is configured but absent from the database."""


class Executor(Protocol):
    async def run(self, query: ValidatedQuery) -> list[dict[str, Any]]: ...


class PsycopgExecutor:
    """Executes against the app's shared psycopg pool."""

    def __init__(self, *, timeout_ms: int = 5_000, reader_role: str = "") -> None:
        self._timeout_ms = int(timeout_ms)
        if self._timeout_ms <= 0:
            raise ValueError(f"timeout_ms must be positive, got {timeout_ms}")
        # Interpolated into SQL below because Postgres SET takes no bind
        # parameters. It comes from Settings and never from the model, and the
        # int() above is what makes that safe.
        if reader_role and not reader_role.replace("_", "").isalnum():
            raise ValueError(f"invalid reader role name: {reader_role!r}")
        self._reader_role = reader_role
        self._gate: asyncio.Semaphore | None = None

    def _semaphore(self) -> asyncio.Semaphore:
        """Created on first use, not at import: a Semaphore built before the
        event loop exists is fragile across loop restarts (notably in tests)."""
        if self._gate is None:
            self._gate = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)
        return self._gate

    async def run(self, query: ValidatedQuery) -> list[dict[str, Any]]:
        pool = get_pool()
        # conn.transaction() is what emits BEGIN, because the pool runs with
        # autocommit=True. Without it every SET in _harden would be a no-op or,
        # worse, would persist on the connection after it returns to the pool —
        # the same pool the checkpointer writes through.
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

        if not self._reader_role:
            return
        try:
            await conn.execute(
                pgsql.SQL("SET LOCAL ROLE {}").format(pgsql.Identifier(self._reader_role))
            )
        except Exception as exc:
            # Fail CLOSED. Falling through would run the query as the database
            # owner, which is a superuser — the precise thing the role exists to
            # prevent. Caught here rather than left to errors.py because a
            # 42501 from a missing SET ROLE would be reported as "that table is
            # not readable", which sends the model chasing the wrong problem.
            if getattr(exc, "sqlstate", None) == UNDEFINED_OBJECT:
                raise ReaderRoleMissing(
                    f"the {self._reader_role!r} role does not exist in this database; "
                    "run `make migrate` to apply db/migrations/0001_sql_reader_role.sql"
                ) from exc
            raise

"""Access to the shared psycopg connection pool (opened in the app lifespan)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Annotated

from fastapi import Depends, Request
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

# Set once by the lifespan. Agent tools read it through get_pool() because they
# run outside any request; routers should take PoolDep instead.
pool: AsyncConnectionPool | None = None


def get_pool() -> AsyncConnectionPool:
    if pool is None:
        raise RuntimeError("Database pool is not initialised (app lifespan not started)")
    return pool


# The pool as the owner. Only identity code takes it: it decides who the caller is, and writes users and
# threads rows no caller may write. Overridable via dependency_overrides[get_pool], which is how the unit
# tests keep a real database.
OwnerPoolDep = Annotated[AsyncConnectionPool, Depends(get_pool)]


_SET_CALLER = "SELECT set_config('role', %s, true), set_config('request.jwt.claims', %s, true)"


async def set_caller(conn: AsyncConnection, role: str, claims: str) -> None:
    """Run the rest of this transaction as the caller, so RLS applies. SET LOCAL: it ends with the transaction."""
    await conn.execute(_SET_CALLER, (role, claims))


# The (role, claims) an Ask Sangam run queries as, set per /agent request. Unset, its SQL runs as anon.
agent_caller: ContextVar[tuple[str, str] | None] = ContextVar("agent_caller", default=None)
# Tables whose caveats Ask's SQL tools have given in full this turn; a fresh set per /agent request. Unset, every result gives them.
caveats_given: ContextVar[set[str] | None] = ContextVar("caveats_given", default=None)


class CallerPool:
    """The shared pool, with every connection running as the caller rather than the owner.

    Each connection is one transaction that first sets the Postgres role (anon or authenticated) and the
    token claims app.user_id() and the other access functions read. Both are SET LOCAL, so they end with
    the transaction, on error too, and the connection goes back to the pool as the owner: the checkpointer
    and the agent tools, which share it, never inherit a caller.
    """

    def __init__(self, pool: AsyncConnectionPool, *, role: str, claims: str):
        self._pool = pool
        self._role = role
        self._claims = claims

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        async with self._pool.connection() as conn, conn.transaction():
            await set_caller(conn, self._role, self._claims)
            yield conn


def get_caller_pool(request: Request, owner: OwnerPoolDep) -> CallerPool:
    """The pool as this request's caller, whom AuthMiddleware put on the request. Without it, anon."""
    state = request.state
    return CallerPool(owner, role=getattr(state, "db_role", "anon"), claims=getattr(state, "db_claims", ""))


# What every router takes. A route runs as its caller without asking; Ask Sangam's SQL tools, which run
# outside any request, take the caller from agent_caller instead.
PoolDep = Annotated[CallerPool, Depends(get_caller_pool)]

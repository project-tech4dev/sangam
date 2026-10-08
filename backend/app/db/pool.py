"""Access to the shared psycopg connection pool (opened in the app lifespan)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
            await conn.execute(
                "SELECT set_config('role', %s, true), set_config('request.jwt.claims', %s, true)",
                (self._role, self._claims),
            )
            yield conn


def get_caller_pool(request: Request, owner: OwnerPoolDep) -> CallerPool:
    """The pool as this request's caller, whom AuthMiddleware put on the request. Without it, anon."""
    state = request.state
    return CallerPool(owner, role=getattr(state, "db_role", "anon"), claims=getattr(state, "db_claims", ""))


# What every router takes. A route runs as its caller without asking; agent tools, which run outside any
# request, keep the owner through get_pool() until Ask Sangam runs as the caller too (step 8).
PoolDep = Annotated[CallerPool, Depends(get_caller_pool)]

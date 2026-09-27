"""Access to the shared psycopg connection pool (opened in the app lifespan)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from psycopg_pool import AsyncConnectionPool

# Set once by the lifespan. Agent tools read it through get_pool() because they
# run outside any request; routers should take PoolDep instead.
pool: AsyncConnectionPool | None = None


def get_pool() -> AsyncConnectionPool:
    if pool is None:
        raise RuntimeError("Database pool is not initialised (app lifespan not started)")
    return pool


# Routers declare `pool: PoolDep` rather than calling get_pool() in the body. That makes the pool
# overridable per-app via dependency_overrides[get_pool], which is how the unit tests keep a real database.
PoolDep = Annotated[AsyncConnectionPool, Depends(get_pool)]

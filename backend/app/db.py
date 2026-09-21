"""Access to the shared psycopg connection pool (opened in the app lifespan)."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

# Set once by the lifespan; tools import this module and read the pool lazily
# so they don't need FastAPI request context.
pool: AsyncConnectionPool | None = None


def get_pool() -> AsyncConnectionPool:
    if pool is None:
        raise RuntimeError("Database pool is not initialised (app lifespan not started)")
    return pool

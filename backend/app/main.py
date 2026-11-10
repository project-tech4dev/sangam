"""Application factory and the ASGI entrypoint (`app.main:app`)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.errors import InsufficientPrivilege

from app.api.router import OPENAPI_TAGS, api_router
from app.core.config import Settings, get_settings
from app.core.lifespan import build_lifespan
from app.core.logging import configure_logging
from app.core.security import AuthMiddleware
from app.db import pool as db_pool

# Counts only, so an open path may show them: whether requests are queuing for a connection.
_POOL_STATS = ("pool_max", "pool_size", "pool_available", "requests_waiting", "requests_errors", "connections_errors")


def _pool_stats() -> dict[str, Any]:
    if db_pool.pool is None:
        return {}
    stats = db_pool.pool.get_stats()
    return {"pool": {key: stats.get(key, 0) for key in _POOL_STATS}}


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Takes settings so tests can build a variant."""
    resolved = settings or get_settings()
    configure_logging()

    app = FastAPI(
        title="Sangam API",
        lifespan=build_lifespan(resolved),
        openapi_tags=OPENAPI_TAGS,
        # Langfuse drops HTTP spans, but as parents they would leave each agent run without a trace root.
        telemetry={"tracing": False},
    )
    # Added first, so CORS wraps it: preflights are answered before it runs, and its 401s carry CORS headers.
    app.add_middleware(AuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.origins,
        # None rather than "" — an empty pattern matches every origin.
        allow_origin_regex=resolved.allowed_origin_regex or None,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    # A request runs as anon or authenticated; a table that role was not granted is a refusal, not a crash.
    @app.exception_handler(InsufficientPrivilege)
    async def _not_allowed(request: Request, exc: InsufficientPrivilege) -> JSONResponse:
        return JSONResponse({"detail": "Not allowed"}, status_code=403)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", **_pool_stats()}

    return app


app = create_app()

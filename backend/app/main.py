"""Application factory and the ASGI entrypoint (`app.main:app`)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import OPENAPI_TAGS, api_router
from app.core.config import Settings, get_settings
from app.core.lifespan import build_lifespan
from app.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Takes settings so tests can build a variant."""
    resolved = settings or get_settings()
    configure_logging()

    app = FastAPI(
        title="Sangam API",
        lifespan=build_lifespan(resolved),
        openapi_tags=OPENAPI_TAGS,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.origins,
        # None rather than "" — an empty pattern matches every origin.
        allow_origin_regex=resolved.allowed_origin_regex or None,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

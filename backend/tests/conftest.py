"""Test scaffolding: stub apps per router (no lifespan → no pool/agent/model).

Unit tests monkeypatch repository functions, so no database is required.
Integration tests (marked) hit the compose Postgres on localhost:5433.
"""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.auth import DEV_USER_ID, get_current_user
from app.db import get_pool

TEST_USER = UUID("00000000-0000-0000-0000-000000000001")


class _SentinelPool:
    """Inert stand-in handed to monkeypatched repositories; any real use fails."""

    def __getattr__(self, name):
        raise AssertionError("unit test used the pool — monkeypatch the repository instead")


def make_app(*routers) -> FastAPI:
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    # Routers resolve the pool through Depends(get_pool), so one override covers
    # every router — no per-module list to keep in sync when a resource is added.
    app.dependency_overrides[get_pool] = _SentinelPool
    return app


@pytest.fixture
def client_for():
    def _make(*routers) -> httpx.AsyncClient:
        app = make_app(*routers)
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _make


assert DEV_USER_ID == TEST_USER  # auth stub and tests agree on the dev identity

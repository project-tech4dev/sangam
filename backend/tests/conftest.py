"""Test scaffolding: stub apps per router (no lifespan → no pool/agent/model)."""

from __future__ import annotations

import os
from uuid import UUID

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from psycopg.rows import dict_row

from app.core.security import DEV_USER, DEV_USER_ID, get_current_user, get_principal
from app.db.pool import get_pool

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
    app.dependency_overrides[get_principal] = lambda: DEV_USER
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

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")


@pytest.fixture
async def db():
    """An async connection to the compose Postgres, rolled back afterwards.

    For the integration tier only. Unit tests get _SentinelPool and must
    monkeypatch the repository instead.
    """
    try:
        conn = await psycopg.AsyncConnection.connect(
            DSN, connect_timeout=3, row_factory=dict_row, autocommit=False
        )
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    async with conn:
        yield conn
        await conn.rollback()  # never leave a test row behind


@pytest.fixture
def build_import(monkeypatch):
    """Builds the Import agent and returns what create_deep_agent received; each model is a fake named by its spec."""
    from types import SimpleNamespace

    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from app.core.config import Settings
    from app.ingest import agent, middleware

    def fake(spec: str) -> FakeListChatModel:
        return FakeListChatModel(responses=["ok"], name=spec)

    def _build(**overrides):
        seen: dict = {}

        def capture(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(with_config=lambda config: seen.setdefault("config", config))

        monkeypatch.setattr(agent, "resolve_model", fake)
        monkeypatch.setattr(middleware, "resolve_model", fake)
        monkeypatch.setattr(agent, "create_deep_agent", capture)
        agent.build_ingest_agent(Settings(**overrides), None)
        return seen

    return _build

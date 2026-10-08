import json
from types import SimpleNamespace
from uuid import UUID

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from psycopg.errors import InsufficientPrivilege
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.security import ANONYMOUS, DEV_USER, CurrentUser, _db_identity
from app.db.pool import CallerPool, get_caller_pool
from app.main import create_app
from tests.conftest import DSN, _SentinelPool

MEMBER = CurrentUser(
    id=UUID("11111111-2222-3333-4444-555555555555"),
    is_staff=False,
    auth_user_id=UUID("6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f"),
    email="person@ngo.org",
)


def test_signed_out_runs_as_anon_with_no_claims():
    assert _db_identity(ANONYMOUS) == ("anon", "")


def test_signed_in_runs_as_authenticated_with_the_token_subject():
    role, claims = _db_identity(MEMBER)
    assert role == "authenticated"
    assert json.loads(claims)["sub"] == str(MEMBER.auth_user_id)


def test_the_dev_user_carries_a_subject():
    assert json.loads(_db_identity(DEV_USER)[1])["sub"] == str(DEV_USER.id)


def test_routers_get_the_caller_the_middleware_left():
    request = SimpleNamespace(state=SimpleNamespace(db_role="authenticated", db_claims='{"sub": "x"}'))
    pool = get_caller_pool(request, _SentinelPool())
    assert (pool._role, pool._claims) == ("authenticated", '{"sub": "x"}')


def test_without_the_middleware_a_router_runs_as_anon():
    pool = get_caller_pool(SimpleNamespace(state=SimpleNamespace()), _SentinelPool())
    assert pool._role == "anon"


async def test_a_table_the_role_may_not_use_is_403():
    app: FastAPI = create_app()

    @app.get("/boom")
    async def boom():
        raise InsufficientPrivilege("permission denied for table proposals")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/boom")
    assert response.status_code == 403
    assert response.json() == {"detail": "Not allowed"}


@pytest.fixture
async def real_pool():
    try:
        await (await psycopg.AsyncConnection.connect(DSN, connect_timeout=3)).close()
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    pool = AsyncConnectionPool(
        DSN, min_size=1, max_size=1, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    yield pool
    await pool.close()


@pytest.mark.integration
async def test_queries_run_as_the_caller_and_the_connection_returns_as_the_owner(real_pool):
    anon = CallerPool(real_pool, role="anon", claims="")
    async with anon.connection() as conn:
        assert (await (await conn.execute("SELECT current_user AS u")).fetchone())["u"] == "anon"
        await conn.execute("SELECT 1 FROM orgs LIMIT 1")

    with pytest.raises(InsufficientPrivilege):
        async with anon.connection() as conn:
            await conn.execute("SELECT 1 FROM proposals")

    async with real_pool.connection() as conn:  # max_size=1: the same connection, back in the pool
        row = await (await conn.execute(
            "SELECT current_user AS u, current_setting('request.jwt.claims', true) AS claims"
        )).fetchone()
    assert row["u"] != "anon"
    assert not row["claims"]


@pytest.mark.integration
async def test_the_access_functions_see_the_dev_user(real_pool):
    async with real_pool.connection() as conn:
        staff = (await (await conn.execute(
            "SELECT is_staff FROM users WHERE id = %s", (DEV_USER.id,)
        )).fetchone())["is_staff"]
    dev = CallerPool(real_pool, role="authenticated", claims=_db_identity(DEV_USER)[1])
    async with dev.connection() as conn:
        row = await (await conn.execute("SELECT app.user_id() AS id, app.is_staff() AS staff")).fetchone()
    assert row == {"id": DEV_USER.id, "staff": staff}

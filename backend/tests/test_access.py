from uuid import UUID

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse

from app.api.routes import contacts, ingest
from app.core import security
from app.core.security import (
    ANONYMOUS,
    DEV_USER,
    CurrentUser,
    chat_access,
    chat_user_id,
    get_current_user,
    get_principal,
    staff_chat_access,
)
from tests.conftest import make_app

MEMBER = CurrentUser(id=UUID("11111111-2222-3333-4444-555555555555"), is_staff=False)
OTHER = UUID("99999999-8888-7777-6666-555555555555")


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def as_caller(app: FastAPI, principal: CurrentUser) -> FastAPI:
    app.dependency_overrides[get_principal] = lambda: principal
    app.dependency_overrides[get_current_user] = lambda: principal.id
    return app


async def test_saving_signed_out_is_401():
    app = as_caller(make_app(contacts.router), ANONYMOUS)
    async with client(app) as c:
        response = await c.post("/api/contacts", json={})
    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in required"


@pytest.mark.parametrize(("principal", "status"), [(ANONYMOUS, 401), (MEMBER, 403)])
async def test_import_routes_need_staff(principal, status):
    app = as_caller(make_app(ingest.router), principal)
    async with client(app) as c:
        response = await c.get("/api/ingest/sources")
    assert response.status_code == status


async def test_import_routes_open_to_staff():
    app = as_caller(make_app(ingest.router), DEV_USER)
    async with client(app) as c:
        response = await c.get("/api/ingest/sources")
    assert response.status_code == 200


@pytest.fixture
def owners(monkeypatch):
    """Thread ownership as a dict; claim_thread claims a thread no one owns yet."""
    table: dict[str, UUID] = {"theirs": OTHER}

    async def claim(pool, *, thread_id, user_id, **_):
        return table.setdefault(thread_id, user_id)

    monkeypatch.setattr(security.threads, "claim_thread", claim)
    return table


def chat_app(principal: CurrentUser, access=chat_access) -> FastAPI:
    app = make_app()

    @app.post("/agent", dependencies=[Depends(access)])
    async def agent():
        async def stream():
            yield str(chat_user_id.get())

        return StreamingResponse(stream())

    return as_caller(app, principal)


async def run(app: FastAPI, thread_id: str) -> httpx.Response:
    async with client(app) as c:
        return await c.post("/agent", json={"threadId": thread_id, "runId": "r1", "messages": []})


async def test_a_new_thread_is_claimed_and_the_run_knows_who_asked(owners):
    response = await run(chat_app(MEMBER), "new")
    assert response.status_code == 200
    assert response.text == str(MEMBER.id)
    assert owners["new"] == MEMBER.id


async def test_someone_elses_thread_is_404(owners):
    response = await run(chat_app(MEMBER), "theirs")
    assert response.status_code == 404


async def test_staff_may_open_any_thread(owners):
    response = await run(chat_app(DEV_USER), "theirs")
    assert response.status_code == 200


async def test_chat_signed_out_is_401(owners):
    response = await run(chat_app(ANONYMOUS), "new")
    assert response.status_code == 401
    assert "new" not in owners


async def test_import_chat_needs_staff(owners):
    response = await run(chat_app(MEMBER, staff_chat_access), "new")
    assert response.status_code == 403

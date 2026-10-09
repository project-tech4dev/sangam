import re
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.api.routes import ingest
from app.core.security import ANONYMOUS, get_current_user, get_principal, require_staff
from app.repositories import threads as threads_repo
from tests.conftest import TEST_USER, make_app
from tests.test_access import MEMBER, client


def app_with(graph=None):
    app = make_app(ingest.router)
    app.state.ingest_graph = graph
    return app


class _Graph:
    async def aget_state(self, config):
        assert config["configurable"]["thread_id"] == "import-1"
        return SimpleNamespace(values={"messages": []})


@pytest.fixture
def owner_pool(monkeypatch):
    # The messages route reads the owner pool directly; the access check is the repository's.
    async def can_open(pool, *, thread_id, user_id):
        return thread_id != "import-2"

    monkeypatch.setattr("app.api.routes.threads.repo.can_open", can_open)


async def test_lists_only_import_threads(monkeypatch):
    seen = {}

    async def fake(pool, *, user_id, kind, limit=50):
        seen["kind"] = kind
        return [{"thread_id": "import-1", "title": "Research ATE", "created_at": "2026-10-09T10:00:00Z",
                 "updated_at": "2026-10-09T10:05:00Z"}]

    monkeypatch.setattr("app.api.routes.ingest.threads_repo.list_threads", fake)
    async with client(app_with()) as c:
        response = await c.get("/api/ingest/threads")
    assert response.status_code == 200 and seen["kind"] == "import"
    assert [t["thread_id"] for t in response.json()] == ["import-1"]


async def test_messages_of_an_import_thread(owner_pool):
    async with client(app_with(_Graph())) as c:
        response = await c.get("/api/ingest/threads/import-1/messages")
    assert response.status_code == 200 and response.json() == {"thread_id": "import-1", "messages": []}


@pytest.mark.parametrize("thread_id", ["import-2", "a-chat-the-caller-owns"])
async def test_someone_elses_or_an_ask_thread_is_404(owner_pool, thread_id):
    async with client(app_with(_Graph())) as c:
        response = await c.get(f"/api/ingest/threads/{thread_id}/messages")
    assert response.status_code == 404


async def test_without_the_graph_is_503(owner_pool):
    async with client(app_with(None)) as c:
        response = await c.get("/api/ingest/threads/import-1/messages")
    assert response.status_code == 503


async def test_signed_out_cannot_list_import_threads():
    app = app_with()
    app.dependency_overrides[get_principal] = lambda: ANONYMOUS
    app.dependency_overrides[get_current_user] = lambda: None
    async with client(app) as c:
        response = await c.get("/api/ingest/threads")
    assert response.status_code == 401


async def test_the_access_check_is_for_the_caller(monkeypatch):
    seen = {}

    async def can_open(pool, *, thread_id, user_id):
        seen["user_id"] = user_id
        return False

    monkeypatch.setattr("app.api.routes.threads.repo.can_open", can_open)
    async with client(app_with(_Graph())) as c:
        response = await c.get("/api/ingest/threads/import-1/messages")
    assert response.status_code == 404 and seen["user_id"] == TEST_USER


# Scoped to the caller inside the route; every other Import route is staff's.
OPEN_ROUTES = {"/ingest/research", "/ingest/research/{slug}/review", "/ingest/research/{slug}/coverage",
               "/ingest/threads", "/ingest/threads/{thread_id}/messages"}


def _staff_only(route) -> bool:
    return any(d.dependency is require_staff for d in route.dependencies)


def test_only_research_and_threads_are_open_to_members():
    assert {r.path for r in ingest.router.routes if not _staff_only(r)} == OPEN_ROUTES


def _route_urls():
    for route in ingest.router.routes:
        if route.path in OPEN_ROUTES:
            continue
        path = re.sub(r"\{[^}]+\}", lambda m: "import-1" if m.group(0) == "{thread_id}" else "1", route.path)
        for method in route.methods:
            yield method, path


@pytest.mark.parametrize(("method", "path"), sorted(_route_urls()))
async def test_every_other_import_route_is_staff_only(method, path):
    app = app_with(_Graph())
    app.dependency_overrides[get_principal] = lambda: MEMBER
    app.dependency_overrides[get_current_user] = lambda: MEMBER.id
    async with client(app) as c:
        response = await c.request(method, f"/api{path}", json={"answer": "not_sure"})
    assert response.status_code == 403


class _Conn:
    def __init__(self, seen):
        self.seen = seen

    async def execute(self, sql, params):
        self.seen.append(sql)
        return self

    async def fetchall(self):
        return []


class _RecordingPool:
    def __init__(self):
        self.sql = []

    @asynccontextmanager
    async def connection(self):
        yield _Conn(self.sql)


@pytest.mark.parametrize(("kind", "filter_"), [("import", "thread_id LIKE"), ("ask", "thread_id NOT LIKE")])
async def test_thread_listing_sql_is_fixed_per_kind(kind, filter_):
    pool = _RecordingPool()
    await threads_repo.list_threads(pool, user_id=TEST_USER, kind=kind)
    assert filter_ in pool.sql[0] and "%(user_id)s" in pool.sql[0]


async def test_an_unknown_kind_fails_rather_than_listing_ask_chats():
    with pytest.raises(KeyError):
        await threads_repo.list_threads(_RecordingPool(), user_id=TEST_USER, kind="anything")

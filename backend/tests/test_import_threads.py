from types import SimpleNamespace

import pytest

from app.api.routes import ingest
from app.core.security import get_principal
from tests.conftest import make_app
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


async def test_members_cannot_list_import_threads():
    app = app_with()
    app.dependency_overrides[get_principal] = lambda: MEMBER
    async with client(app) as c:
        response = await c.get("/api/ingest/threads")
    assert response.status_code == 403

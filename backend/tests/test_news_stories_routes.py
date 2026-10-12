"""The story routes: a bad cursor is a 400, not a 500; the hide route is staff only."""

from uuid import uuid4

import httpx

from app.api.routes import news_stories
from app.core.security import ANONYMOUS, CurrentUser, get_principal
from tests.conftest import make_app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_a_bad_cursor_is_a_400(monkeypatch):
    async def boom(*a, **k):
        raise ValueError("bad cursor")
    monkeypatch.setattr(news_stories.repo, "list_stories", boom)
    async with _client(make_app(news_stories.router)) as client:
        r = await client.get("/api/news/stories", params={"cursor": "x"})
    assert r.status_code == 400


async def test_hiding_is_for_staff():
    app = make_app(news_stories.router)
    app.dependency_overrides[get_principal] = lambda: CurrentUser(id=uuid4(), is_staff=False, auth_user_id=uuid4())
    async with _client(app) as client:
        r = await client.post("/api/news/stories/1/hide", json={"org_id": 1})
    assert r.status_code == 403


async def test_the_list_needs_sign_in():
    app = make_app(news_stories.router)
    app.dependency_overrides[get_principal] = lambda: ANONYMOUS
    async with _client(app) as client:
        r = await client.get("/api/news/stories")
    assert r.status_code == 401


async def _area_for(monkeypatch, staff: bool, **params) -> tuple[str, dict]:
    seen = {}

    async def fake(pool, f, **k):
        seen["area"] = f.area
        return {"items": [], "next_cursor": None, "counts": {"org": 0, "funder": 0, "general": 0}}

    async def last(pool):
        return "2031-01-02"
    monkeypatch.setattr(news_stories.repo, "list_stories", fake)
    monkeypatch.setattr(news_stories.repo, "last_pull", last)
    app = make_app(news_stories.router)
    app.dependency_overrides[get_principal] = lambda: CurrentUser(id=uuid4(), is_staff=staff, auth_user_id=uuid4())
    async with _client(app) as client:
        r = await client.get("/api/news/stories", params=params)
    return seen["area"], r.json()


async def test_area_defaults_to_mine_for_a_member_and_everywhere_for_staff(monkeypatch):
    area, body = await _area_for(monkeypatch, staff=False)
    assert area == "mine" and body["last_pull"] == "2031-01-02"
    assert (await _area_for(monkeypatch, staff=True))[0] == "all"
    assert (await _area_for(monkeypatch, staff=False, area="north_east"))[0] == "north_east"

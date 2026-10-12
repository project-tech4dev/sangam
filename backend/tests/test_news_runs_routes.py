"""The news plan route: staff only, writes nothing, and says which names it found (spec 2b, Scout's approval card)."""

from datetime import date
from uuid import uuid4

import httpx

from app.api.routes import news_runs
from app.core.security import CurrentUser, get_principal
from app.ingest.news.feeds import Subject
from app.ingest.news.pipeline import Selection
from tests.conftest import make_app

MEMBER = CurrentUser(id=uuid4(), is_staff=False, auth_user_id=uuid4())
TWO = [Subject("org", 1, "a", "Org A"), Subject("org", 2, "b", "Org B", searched_through=date.today()),
       Subject("feed", None, "fcra", "FCRA", searched_through=date.today())]


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _patch(monkeypatch, selection):
    seen = {}

    async def select(pool, names):
        seen["names"] = names
        return selection

    async def subjects(pool, **kw):
        seen.update(kw)
        return TWO if (kw["org_ids"] is None or kw["org_ids"]) else []
    monkeypatch.setattr(news_runs.pipeline, "select", select)
    monkeypatch.setattr(news_runs.pipeline, "plan_subjects", subjects)
    return seen


async def test_no_names_plans_everyone(monkeypatch):
    seen = _patch(monkeypatch, Selection(None, None, ["fcra", "csr_trends", "ngo_north_east"], [], []))
    async with _client(make_app(news_runs.router)) as client:
        r = await client.get("/api/ingest/news-runs/plan")
    body = r.json()
    assert r.status_code == 200 and body["everyone"] and body["subjects"] == 3 and body["newcomers"] == 1
    assert body["records"] == 2  # organisations and funders; the topic feeds are counted apart
    assert seen["names"] == [] and seen["org_ids"] is None


async def test_names_are_split_and_reported_matched_or_not(monkeypatch):
    seen = _patch(monkeypatch, Selection([4], [], [], ["KABIL"], ["Nobody Trust"]))
    async with _client(make_app(news_runs.router)) as client:
        r = await client.get("/api/ingest/news-runs/plan", params={"names": "KABIL, Nobody Trust"})
    body = r.json()
    assert seen["names"] == ["KABIL", "Nobody Trust"]
    assert not body["everyone"] and body["matched"] == ["KABIL"] and body["unmatched"] == ["Nobody Trust"]


async def test_names_that_match_nothing_plan_nothing_not_everyone(monkeypatch):
    _patch(monkeypatch, Selection([], [], [], [], ["Nobody Trust"]))
    async with _client(make_app(news_runs.router)) as client:
        body = (await client.get("/api/ingest/news-runs/plan", params={"names": "Nobody Trust"})).json()
    assert body["subjects"] == 0 and not body["everyone"]


async def test_the_form_routes_are_gone():
    async with _client(make_app(news_runs.router)) as client:
        assert (await client.post("/api/ingest/news-runs", json={})).status_code in (404, 405)
        assert (await client.post("/api/ingest/news-runs/1/execute")).status_code in (404, 405)


async def test_non_staff_are_refused():
    app = make_app(news_runs.router)
    app.dependency_overrides[get_principal] = lambda: MEMBER
    async with _client(app) as client:
        assert (await client.get("/api/ingest/news-runs/plan")).status_code == 403

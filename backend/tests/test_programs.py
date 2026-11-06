"""Programs: paged through fetch_page, answered through build_page."""

from app.api.routes import programs as programs_api
from app.repositories.programs import list_programs
from tests.test_paging import _Pool


async def test_list_programs_pages_its_filters_through_fetch_page():
    pool = _Pool([{"id": 6, "total": 20}])
    rows, total = await list_programs(pool, limit=2, offset=6, org="kabil", status="active")
    assert ([r["id"] for r in rows], total) == ([6], 20)
    assert pool.sql.rstrip().endswith("LIMIT %(limit)s OFFSET %(offset)s")
    assert pool.params["org"] == "kabil" and pool.params["status"] == "active"
    assert (pool.params["limit"], pool.params["offset"]) == (2, 6)


async def test_the_list_answers_with_its_page(client_for, monkeypatch):
    calls = []

    async def fake_list(pool, **kw):
        calls.append(kw)
        return [{"id": 1, "name": "Water"}], 9

    monkeypatch.setattr("app.api.routes.programs.repo.list_programs", fake_list)
    async with client_for(programs_api.router) as client:
        body = (await client.get("/api/programs?org=kabil&limit=2&offset=4")).json()
    assert (body["total"], body["limit"], body["offset"], body["items"][0]["name"]) == (9, 2, 4, "Water")
    assert calls[0]["org"] == "kabil" and (calls[0]["limit"], calls[0]["offset"]) == (2, 4)

"""Funder partner lines: paged through fetch_page, answered through build_page."""

from app.api.routes import partner_lines as partner_lines_api
from app.repositories.partner_lines import list_partner_lines


async def test_list_partner_lines_pages_its_filters_through_fetch_page(recording_pool):
    pool = recording_pool([{"id": 11, "total": 42}])
    rows, total = await list_partner_lines(pool, limit=2, offset=6, funder="axis", status="active")
    assert ([r["id"] for r in rows], total) == ([11], 42)
    assert pool.params["funder"] == "axis" and pool.params["status"] == "active"
    assert (pool.params["limit"], pool.params["offset"]) == (2, 6)


async def test_the_list_answers_with_its_page(client_for, monkeypatch):
    calls = []

    async def fake_list(pool, **kw):
        calls.append(kw)
        return [{"id": 1, "funder_id": 29, "funder_slug": "axis", "funder_name": "Axis Bank Foundation",
                 "fiscal_year": "FY2024-25", "partner_name": "KABIL"}], 9

    monkeypatch.setattr("app.api.routes.partner_lines.repo.list_partner_lines", fake_list)
    async with client_for(partner_lines_api.router) as client:
        body = (await client.get("/api/partner-lines?funder=axis&limit=2&offset=4")).json()
    assert (body["total"], body["limit"], body["offset"]) == (9, 2, 4)
    assert body["items"][0]["partner_name"] == "KABIL"
    assert calls[0]["funder"] == "axis" and (calls[0]["limit"], calls[0]["offset"]) == (2, 4)

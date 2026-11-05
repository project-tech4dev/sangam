"""The tag vocabulary and location lists: paged through fetch_page, answered through build_page."""

from app.api.routes import meta as meta_api
from app.repositories.meta import list_locations, list_tags
from tests.test_paging import _Pool


async def test_list_tags_pages_its_filters_through_fetch_page():
    pool = _Pool([{"id": 1, "total": 40}])
    rows, total = await list_tags(pool, limit=2, offset=6, kind="theme", q="liveli")
    assert ([r["id"] for r in rows], total) == ([1], 40)
    assert pool.sql.rstrip().endswith("LIMIT %(limit)s OFFSET %(offset)s")
    assert pool.params == {"kind": "theme", "q": "liveli", "limit": 2, "offset": 6}


async def test_list_locations_pages_its_filters_through_fetch_page():
    pool = _Pool([])
    assert await list_locations(pool, limit=50, offset=0, kind="district", parent=18) == ([], 0)
    assert pool.params == {"kind": "district", "parent": 18, "limit": 50, "offset": 0}


async def test_the_tag_and_location_lists_answer_with_their_page(client_for, monkeypatch):
    calls = []

    def fake(rows):
        async def list_fn(pool, **kw):
            calls.append(kw)
            return rows, 9
        return list_fn

    monkeypatch.setattr("app.api.routes.meta.repo.list_tags",
                        fake([{"id": 1, "slug": "health", "label": "Health", "kind": "theme"}]))
    monkeypatch.setattr("app.api.routes.meta.repo.list_locations", fake([{"id": 2, "kind": "state", "name": "Assam"}]))
    async with client_for(meta_api.router) as client:
        tags = (await client.get("/api/meta/tags?kind=theme&limit=2&offset=4")).json()
        places = (await client.get("/api/meta/locations?kind=state")).json()
    assert (tags["total"], tags["limit"], tags["offset"], tags["items"][0]["label"]) == (9, 2, 4, "Health")
    assert (places["limit"], places["offset"], places["items"][0]["name"]) == (50, 0, "Assam")
    assert calls[0]["kind"] == "theme" and calls[1]["kind"] == "state"

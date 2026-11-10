"""The Registry list: one call, every row with what its filters read, research counted on the owner."""

from app.api.routes import registry as registry_api
from app.repositories.registry import Filters

ROUTE = "app.api.routes.registry"

ROWS = [
    {"kind": "org", "id": 4, "slug": "kabil", "name": "KABIL", "place": "Udalguri, Assam",
     "states": ["Assam", "Rajasthan"], "themes": [{"label": "Livelihood diversification", "domain": "Livelihoods"}],
     "populations": ["Women"], "sdgs": ["1", "5"], "csr1": False, "has_12a_80g": True, "fcra": True,
     "press": 0, "social": 6, "posts_since": "2026-08-04", "search": "udalguri kabil india"},
    {"kind": "funder", "id": 29, "slug": "axis-bank-foundation", "name": "Axis Bank Foundation",
     "funder_type": "corporate_foundation", "states": ["Meghalaya"], "intake_mode": "invitation_only",
     "partners": 42, "csr_prescribed": 4259200000, "csr_year": "FY2024-25"},
]


def _patch(monkeypatch, rows=ROWS, research=None):
    async def entries(pool, owner):
        return [dict(r) for r in rows]

    async def counts(pool, entities):
        counts.calls.append(entities)
        return research if research is not None else {("org", 4): {"runs": 4, "latest": "2026-10-13"}}
    counts.calls = []

    async def page(pool, owner, f, *, limit, offset):
        page.calls.append((f, limit, offset))
        items = [dict(r) for r in rows][:limit]
        return {"items": items, "total": len(rows) + offset, "limit": limit, "offset": offset,
                "counts": {"all": 2, "org": 1, "funder": 1}, "facets": {"where": [{"value": "Assam", "count": 1}]}}
    page.calls = []
    counts.page = page

    monkeypatch.setattr(f"{ROUTE}.repo.registry_rows", entries)
    monkeypatch.setattr(f"{ROUTE}.repo.registry_page_sql", page)
    monkeypatch.setattr(f"{ROUTE}.repo.research_counts", counts)
    return counts


async def test_registry_serves_every_row_with_its_research(client_for, monkeypatch):
    counts = _patch(monkeypatch)
    async with client_for(registry_api.router) as client:
        response = await client.get("/api/registry")
    assert response.status_code == 200
    rows = {r["slug"]: r for r in response.json()["rows"]}
    assert rows["kabil"]["research_runs"] == 4 and rows["kabil"]["researched_on"] == "2026-10-13"
    assert rows["axis-bank-foundation"]["research_runs"] == 0
    assert rows["kabil"]["themes"][0]["domain"] == "Livelihoods"
    assert (rows["kabil"]["press"], rows["kabil"]["social"]) == (0, 6)
    assert rows["axis-bank-foundation"]["csr_year"] == "FY2024-25"
    assert counts.calls == [[("org", 4, "kabil"), ("funder", 29, "axis-bank-foundation")]]


async def test_research_failure_leaves_the_list_up(client_for, monkeypatch):
    _patch(monkeypatch)

    async def broken(pool, entities):
        raise RuntimeError("owner pool down")

    monkeypatch.setattr(f"{ROUTE}.repo.research_counts", broken)
    async with client_for(registry_api.router) as client:
        response = await client.get("/api/registry")
    assert response.status_code == 200
    assert all(r["research_runs"] == 0 for r in response.json()["rows"])


def test_a_row_leads_with_the_tags_most_of_its_programmes_carry_and_leaves_lenses_out():
    from app.repositories.registry import _themes

    def tag(label, kind, progs, domain="Health"):
        return {"label": label, "kind": kind, "progs": progs, "domain": domain}

    themes, populations = _themes([
        tag("Arts", "sub_theme", 0, "Others"), tag("Primary care", "sub_theme", 3),
        tag("Children", "population", 1), tag("Women", "population", 4), tag("NRM", "sub_theme", 3, "Livelihoods"),
        tag("Climate-smart", "lens", 9),
    ])
    assert [t["label"] for t in themes] == ["Primary care", "NRM", "Arts"]
    assert populations == ["Women", "Children"]


async def _page(client_for, monkeypatch, query, rows=ROWS):
    counts = _patch(monkeypatch, rows=rows)
    async with client_for(registry_api.router) as client:
        return await client.get(f"/api/registry/page{query}"), counts


async def test_a_page_serves_the_repository_page_without_the_search_text(client_for, monkeypatch):
    response, counts = await _page(client_for, monkeypatch, "")
    body = response.json()
    assert response.status_code == 200
    assert [r["slug"] for r in body["items"]] == ["kabil", "axis-bank-foundation"]
    assert all("search" not in r for r in body["items"])
    assert body["counts"] == {"all": 2, "org": 1, "funder": 1} and body["facets"]["where"][0]["value"] == "Assam"
    assert counts.page.calls == [(Filters(), 50, 0)]


async def test_the_query_becomes_the_filters_with_type_named_as_the_address_names_it(client_for, monkeypatch):
    query = "?type=cso&theme=Health&population=Women&sdg=3&where=ne&reg=fcra&q=dalgu&limit=10&offset=20"
    _, counts = await _page(client_for, monkeypatch, query)
    want = Filters(kind="org", theme="Health", population="Women", sdg="3", where="ne", reg="fcra", q="dalgu")
    assert counts.page.calls == [(want, 10, 20)]
    for typ, kind in (("funder", "funder"), ("anything", "all")):
        _, counts = await _page(client_for, monkeypatch, f"?type={typ}&ftype=foundation&approach=open")
        assert counts.page.calls[0][0] == Filters(kind=kind, ftype="foundation", approach="open")


async def test_research_is_read_for_the_page_rows_only(client_for, monkeypatch):
    response, counts = await _page(client_for, monkeypatch, "?limit=1")
    assert [r["slug"] for r in response.json()["items"]] == ["kabil"]
    assert response.json()["items"][0]["research_runs"] == 4
    assert counts.calls == [[("org", 4, "kabil")]]


async def test_an_empty_page_reads_no_research(client_for, monkeypatch):
    response, counts = await _page(client_for, monkeypatch, "?offset=99", rows=[])
    assert response.json()["items"] == [] and response.json()["total"] == 99
    assert counts.calls == []


async def test_a_bad_limit_or_offset_is_refused(client_for, monkeypatch):
    for query in ("?limit=0", "?limit=101", "?offset=-1"):
        response, _ = await _page(client_for, monkeypatch, query)
        assert response.status_code == 422, query


async def test_a_research_failure_leaves_the_page_up(client_for, monkeypatch):
    _patch(monkeypatch)

    async def broken(pool, entities):
        raise RuntimeError("owner pool down")

    monkeypatch.setattr(f"{ROUTE}.repo.research_counts", broken)
    async with client_for(registry_api.router) as client:
        response = await client.get("/api/registry/page?limit=2")
    assert response.status_code == 200 and len(response.json()["items"]) == 2

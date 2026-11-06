"""The Registry list: one call, every row with what its filters read, research counted on the owner."""

from app.api.routes import registry as registry_api
from app.repositories.registry import registry_page

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
        return registry_page([dict(r) for r in rows], f, limit=limit, offset=offset)

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


def _row(kind, id_, name, **over):
    return {"kind": kind, "id": id_, "slug": f"{kind}-{id_}", "name": name, "states": [], "themes": [],
            "populations": [], "sdgs": [], "search": name.lower(), **over}


MANY = [
    _row("funder", 1, "Axis Bank Foundation", funder_type="corporate_foundation", open_call=True,
         states=["Meghalaya"], sdgs=["10"]),
    _row("org", 2, "zeal trust", states=["Goa"], sdgs=["3"]),
    _row("org", 3, "KABIL", states=["Assam"], themes=[{"label": "Livelihoods", "domain": "Livelihoods"}],
         search="kabil udalguri", sdgs=["3", "10"]),
    _row("org", 4, "Aaranyak", states=["Assam"], sdgs=["2"]),
    _row("funder", 5, "Tata Trusts", funder_type="private_foundation", intake_mode="invitation_only"),
]


async def _page(client_for, monkeypatch, query, rows=MANY):
    counts = _patch(monkeypatch, rows=rows)
    async with client_for(registry_api.router) as client:
        return await client.get(f"/api/registry/page{query}"), counts


async def test_a_page_lists_csos_then_funders_each_a_to_z(client_for, monkeypatch):
    response, _ = await _page(client_for, monkeypatch, "")
    body = response.json()
    assert response.status_code == 200
    assert [r["name"] for r in body["items"]] == ["Aaranyak", "KABIL", "zeal trust", "Axis Bank Foundation",
                                                  "Tata Trusts"]
    assert (body["total"], body["limit"], body["offset"]) == (5, 50, 0)
    assert all("search" not in r for r in body["items"])


async def test_limit_and_offset_cut_one_page_and_research_reads_only_it(client_for, monkeypatch):
    response, counts = await _page(client_for, monkeypatch, "?limit=2&offset=2")
    body = response.json()
    assert [r["name"] for r in body["items"]] == ["zeal trust", "Axis Bank Foundation"]
    assert body["total"] == 5
    assert counts.calls == [[("org", 2, "org-2"), ("funder", 1, "funder-1")]]


async def test_filters_and_search_narrow_the_total_but_not_the_cards_or_options(client_for, monkeypatch):
    response, _ = await _page(client_for, monkeypatch, "?type=cso&where=ne&q=dalgu")
    body = response.json()
    assert [r["name"] for r in body["items"]] == ["KABIL"] and body["total"] == 1
    assert body["counts"] == {"all": 5, "org": 3, "funder": 2}
    assert [f["value"] for f in body["facets"]["where"]] == ["Assam", "Goa", "Meghalaya"]
    assert [(f["value"], f["count"]) for f in body["facets"]["sdg"]] == [("2", 1), ("3", 2), ("10", 2)]
    assert [f["value"] for f in body["facets"]["ftype"]] == ["corporate_foundation", "private_foundation"]
    assert {f["value"] for f in body["facets"]["approach"]} == {"open", "invites"}


async def test_funder_filters_apply_under_the_funders_bucket(client_for, monkeypatch):
    response, _ = await _page(client_for, monkeypatch, "?type=funder&approach=invites")
    assert [r["name"] for r in response.json()["items"]] == ["Tata Trusts"]


async def test_an_offset_past_the_end_is_an_empty_page_and_reads_no_research(client_for, monkeypatch):
    response, counts = await _page(client_for, monkeypatch, "?offset=99")
    assert response.json()["items"] == [] and response.json()["total"] == 5
    assert counts.calls == []


async def test_a_bad_limit_or_offset_is_refused(client_for, monkeypatch):
    for query in ("?limit=0", "?limit=101", "?offset=-1"):
        response, _ = await _page(client_for, monkeypatch, query)
        assert response.status_code == 422, query


async def test_a_research_failure_leaves_the_page_up(client_for, monkeypatch):
    _patch(monkeypatch, rows=MANY)

    async def broken(pool, entities):
        raise RuntimeError("owner pool down")

    monkeypatch.setattr(f"{ROUTE}.repo.research_counts", broken)
    async with client_for(registry_api.router) as client:
        response = await client.get("/api/registry/page?limit=2")
    assert response.status_code == 200 and len(response.json()["items"]) == 2

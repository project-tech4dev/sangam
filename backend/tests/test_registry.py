"""The Registry list: one call, every row with what its filters read, research counted on the owner."""

from app.api.routes import registry as registry_api

ROUTE = "app.api.routes.registry"

ROWS = [
    {"kind": "org", "id": 4, "slug": "kabil", "name": "KABIL", "place": "Udalguri, Assam",
     "states": ["Assam", "Rajasthan"], "themes": [{"label": "Livelihood diversification", "domain": "Livelihoods"}],
     "lenses": ["Women & girls"], "sdgs": ["1", "5"], "csr1": False, "has_12a_80g": True, "fcra": True,
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

    monkeypatch.setattr(f"{ROUTE}.repo.registry_rows", entries)
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

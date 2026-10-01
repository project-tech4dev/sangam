from datetime import UTC, datetime

from app.api.routes import orgs as orgs_api

ROW = {
    "id": 1, "slug": "the-ant", "name": "THE ANT", "darpan_id": "AS/2017/0165645",
    "cohort": "core-cohort-2026", "state": "Assam", "district": "CHIRANG",
    "sectors": ["Agriculture", "Education"], "source_name": "darpan-portal",
    "fetched_at": datetime(2026, 9, 21, tzinfo=UTC), "total": 1,
}

LEGACY_KEYS = {"id", "slug", "name", "darpan_id", "cohort", "state", "district",
               "sectors", "source_name", "fetched_at"}


async def test_list_is_legacy_array_shape(client_for, monkeypatch):
    async def fake_list(pool, **kwargs):
        return [ROW], 1

    monkeypatch.setattr("app.api.routes.orgs.repo.list_orgs", fake_list)
    async with client_for(orgs_api.router) as client:
        response = await client.get("/api/orgs")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 1
    assert set(body[0].keys()) == LEGACY_KEYS
    assert body[0]["sectors"] == ["Agriculture", "Education"]


async def test_filters_forwarded(client_for, monkeypatch):
    captured = {}

    async def fake_list(pool, **kwargs):
        captured.update(kwargs)
        return [], 0

    monkeypatch.setattr("app.api.routes.orgs.repo.list_orgs", fake_list)
    async with client_for(orgs_api.router) as client:
        await client.get("/api/orgs", params={"tag": "agriculture", "state": "Assam", "q": "ant"})
    assert captured["tag"] == "agriculture"
    assert captured["state"] == "Assam"
    assert captured["q"] == "ant"
    assert captured["limit"] == 500  # legacy default returns everything


async def test_detail_404(client_for, monkeypatch):
    async def fake_get(pool, slug_or_id):
        return None

    monkeypatch.setattr("app.api.routes.orgs.repo.get_org", fake_get)
    async with client_for(orgs_api.router) as client:
        response = await client.get("/api/orgs/nope")
    assert response.status_code == 200
    assert "not found" in response.json()["detail"]

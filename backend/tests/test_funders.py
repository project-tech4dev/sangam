from app.api import funders as funders_api

ROW = {
    "id": 1, "slug": "axis-bank-foundation", "name": "Axis Bank Foundation",
    "funder_type": "corporate_csr", "website": "https://www.axisbankfoundation.org",
    "focus_sectors": ["sustainable livelihoods"], "geographies": ["Assam", "India"],
    "profile": {"flagship_program": "Sustainable Livelihoods Programme"},
    "latest_scores": {"v1": 93, "v2": 93}, "total": 1,
}

LEGACY_KEYS = {"id", "slug", "name", "funder_type", "website", "focus_sectors",
               "geographies", "profile", "latest_scores"}


async def test_list_is_legacy_array_shape(client_for, monkeypatch):
    async def fake_list(pool, **kwargs):
        return [ROW], 1

    monkeypatch.setattr("app.api.funders.repo.list_funders", fake_list)
    async with client_for(funders_api.router) as client:
        response = await client.get("/api/funders")
    body = response.json()
    assert response.status_code == 200
    assert isinstance(body, list)
    assert set(body[0].keys()) == LEGACY_KEYS
    assert body[0]["latest_scores"] == {"v1": 93, "v2": 93}


async def test_section_135_filter_forwarded(client_for, monkeypatch):
    captured = {}

    async def fake_list(pool, **kwargs):
        captured.update(kwargs)
        return [], 0

    monkeypatch.setattr("app.api.funders.repo.list_funders", fake_list)
    async with client_for(funders_api.router) as client:
        await client.get("/api/funders", params={"section_135": "true"})
    assert captured["section_135"] is True


async def test_scores_404_when_empty(client_for, monkeypatch):
    async def fake_scores(pool, funder_id):
        return []

    monkeypatch.setattr("app.api.funders.repo.funder_scores", fake_scores)
    async with client_for(funders_api.router) as client:
        response = await client.get("/api/funders/99/scores")
    assert response.status_code == 404

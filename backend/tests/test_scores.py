from app.api.routes import scores as scores_api
from tests.conftest import TEST_USER

ADJUSTMENT = {
    "id": 6, "fit_score_id": 1, "criterion_id": 5, "code": "5",
    "old_score": 10, "new_score": 7, "reason": "grant concluded ~March 2022",
    "adjusted_by": str(TEST_USER), "adjusted_at": None,
}


async def test_create_adjustment_stamps_user(client_for, monkeypatch):
    captured = {}

    async def fake_create(pool, fit_score_id, data, adjusted_by):
        captured["adjusted_by"] = adjusted_by
        return ADJUSTMENT

    monkeypatch.setattr("app.api.routes.scores.repo.create_adjustment", fake_create)
    async with client_for(scores_api.router) as client:
        response = await client.post("/api/scores/1/adjustments", json={
            "criterion_id": 5, "old_score": 10, "new_score": 7,
            "reason": "grant concluded ~March 2022",
        })
    assert response.status_code == 201
    assert captured["adjusted_by"] == TEST_USER


async def test_create_adjustment_unknown_score_404(client_for, monkeypatch):
    async def fake_create(pool, fit_score_id, data, adjusted_by):
        return None

    monkeypatch.setattr("app.api.routes.scores.repo.create_adjustment", fake_create)
    async with client_for(scores_api.router) as client:
        response = await client.post("/api/scores/999/adjustments", json={
            "criterion_id": 5, "new_score": 7, "reason": "x",
        })
    assert response.status_code == 404


async def test_adjustment_requires_reason(client_for):
    async with client_for(scores_api.router) as client:
        response = await client.post("/api/scores/1/adjustments", json={
            "criterion_id": 5, "new_score": 7, "reason": "",
        })
    assert response.status_code == 422


async def test_page_envelope_and_limit_clamp(client_for, monkeypatch):
    captured = {}

    async def fake_list(pool, **kwargs):
        captured.update(kwargs)
        return [], 0

    monkeypatch.setattr("app.api.routes.scores.repo.list_scores", fake_list)
    async with client_for(scores_api.router) as client:
        ok = await client.get("/api/scores", params={"limit": 5, "offset": 10})
        too_big = await client.get("/api/scores", params={"limit": 1000})
    body = ok.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert body["limit"] == 5 and body["offset"] == 10
    assert too_big.status_code == 422  # ge/le validation, not silent clamp

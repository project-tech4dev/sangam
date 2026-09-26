from app.api.routes import rfps as rfps_api

MATCH = {
    "rfp_id": 1, "org_id": 9, "org_name": "KABIL", "match_score": 0.9,
    "match_notes": None, "status": "reviewed",
    "matched_by": "00000000-0000-0000-0000-000000000001", "matched_at": None,
}


async def test_patch_match_happy_path(client_for, monkeypatch):
    async def fake_update(pool, rfp_id, org_id, **kwargs):
        assert kwargs["status"] == "reviewed"
        assert kwargs["matched_by"] == "00000000-0000-0000-0000-000000000001"
        return MATCH

    monkeypatch.setattr("app.api.routes.rfps.repo.update_match", fake_update)
    async with client_for(rfps_api.router) as client:
        response = await client.patch("/api/rfps/1/matches/9", json={"status": "reviewed"})
    assert response.status_code == 200
    assert response.json()["status"] == "reviewed"


async def test_patch_match_unknown_pair_404(client_for, monkeypatch):
    async def fake_update(pool, rfp_id, org_id, **kwargs):
        return None

    monkeypatch.setattr("app.api.routes.rfps.repo.update_match", fake_update)
    async with client_for(rfps_api.router) as client:
        response = await client.patch("/api/rfps/1/matches/999", json={"status": "dismissed"})
    assert response.status_code == 404


async def test_patch_match_bad_status_422(client_for):
    async with client_for(rfps_api.router) as client:
        response = await client.patch("/api/rfps/1/matches/9", json={"status": "nonsense"})
    assert response.status_code == 422

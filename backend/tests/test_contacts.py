from app.api.routes import contacts as contacts_api

CREATED = {
    "id": 7, "org_id": None, "funder_id": 2, "name": "A Person", "role": "Grants Lead",
    "kind": "grants", "email": "person@example.org", "phone": None, "verified": False,
    "notes": None, "source_name": "manual", "fetched_at": None,
}


async def test_create_contact_201(client_for, monkeypatch):
    async def fake_create(pool, data):
        assert data["funder_id"] == 2 and data["org_id"] is None
        return CREATED

    monkeypatch.setattr("app.api.routes.contacts.repo.create_contact", fake_create)
    async with client_for(contacts_api.router) as client:
        response = await client.post("/api/contacts", json={
            "funder_id": 2, "name": "A Person", "role": "Grants Lead",
            "kind": "grants", "email": "person@example.org",
        })
    assert response.status_code == 201
    assert response.json()["id"] == 7


async def test_create_rejects_both_and_neither_owner(client_for):
    async with client_for(contacts_api.router) as client:
        both = await client.post("/api/contacts", json={"org_id": 1, "funder_id": 2, "name": "X"})
        neither = await client.post("/api/contacts", json={"name": "X"})
    assert both.status_code == 422
    assert neither.status_code == 422


async def test_create_unknown_owner_404(client_for, monkeypatch):
    async def fake_create(pool, data):
        return None  # FK violation path

    monkeypatch.setattr("app.api.routes.contacts.repo.create_contact", fake_create)
    async with client_for(contacts_api.router) as client:
        response = await client.post("/api/contacts", json={"funder_id": 999, "name": "X"})
    assert response.status_code == 404


async def test_patch_only_sends_set_fields(client_for, monkeypatch):
    captured = {}

    async def fake_get(pool, contact_id):
        return CREATED

    async def fake_update(pool, contact_id, fields):
        captured.update(fields)
        return {**CREATED, **fields}

    monkeypatch.setattr("app.api.routes.contacts.repo.get_contact", fake_get)
    monkeypatch.setattr("app.api.routes.contacts.repo.update_contact", fake_update)
    async with client_for(contacts_api.router) as client:
        response = await client.patch("/api/contacts/7", json={"verified": True})
    assert response.status_code == 200
    assert captured == {"verified": True}  # exclude_unset: nothing else touched

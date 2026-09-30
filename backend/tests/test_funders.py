from app.api.routes import funders as funders_api
from app.core.config import Settings

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

    monkeypatch.setattr("app.api.routes.funders.repo.list_funders", fake_list)
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

    monkeypatch.setattr("app.api.routes.funders.repo.list_funders", fake_list)
    async with client_for(funders_api.router) as client:
        await client.get("/api/funders", params={"section_135": "true"})
    assert captured["section_135"] is True


async def test_scores_404_when_empty(client_for, monkeypatch):
    async def fake_scores(pool, funder_id):
        return []

    monkeypatch.setattr("app.api.routes.funders.repo.funder_scores", fake_scores)
    async with client_for(funders_api.router) as client:
        response = await client.get("/api/funders/99/scores")
    assert response.status_code == 404


# --- the research brief ----------------------------------------------------

class TestFunderBrief:
    """A link to the markdown `make client-docs` renders, served from the
    bucket rather than the repo so the app does not have to read git.
    """

    ROUTE = "app.api.routes.funders"

    def enable(self, monkeypatch):
        monkeypatch.setattr(
            f"{self.ROUTE}.get_settings",
            lambda: Settings(supabase_url="https://p.supabase.co", supabase_service_key="svc"),
        )

    def funder(self, monkeypatch, row):
        async def fake(pool, slug_or_id):
            return row

        monkeypatch.setattr(f"{self.ROUTE}.repo.get_funder", fake)

    async def test_a_researched_funder_gets_a_link(self, client_for, monkeypatch):
        self.enable(monkeypatch)
        self.funder(monkeypatch, {"id": 1, "slug": "sbi-foundation", "name": "SBI Foundation"})
        monkeypatch.setattr(f"{self.ROUTE}.storage.stat", lambda b, k: _async({"name": "x"}))

        async def fake_sign(bucket, key, ttl):
            assert key == "entities/sbi-foundation.md"
            return "https://p.supabase.co/storage/v1/object/sign/x?token=t"

        monkeypatch.setattr(f"{self.ROUTE}.storage.signed_url", fake_sign)
        async with client_for(funders_api.router) as client:
            response = await client.get("/api/funders/sbi-foundation/brief")
        assert response.status_code == 200
        assert response.json()["url"].endswith("token=t")

    async def test_an_unresearched_funder_is_404_not_an_empty_link(
        self, client_for, monkeypatch
    ):
        """Most funders in the catalog have never been researched. A link to a
        brief that does not exist is worse than no link."""
        self.enable(monkeypatch)
        self.funder(monkeypatch, {"id": 1, "slug": "axis-bank-foundation", "name": "ABF"})
        monkeypatch.setattr(f"{self.ROUTE}.storage.stat", lambda b, k: _async(None))
        async with client_for(funders_api.router) as client:
            response = await client.get("/api/funders/axis-bank-foundation/brief")
        assert response.status_code == 404

    async def test_an_unknown_funder_is_404(self, client_for, monkeypatch):
        self.enable(monkeypatch)
        self.funder(monkeypatch, None)
        async with client_for(funders_api.router) as client:
            response = await client.get("/api/funders/nope/brief")
        assert response.status_code == 404

    async def test_no_storage_configured_is_404_not_a_crash(self, client_for, monkeypatch):
        monkeypatch.setattr(f"{self.ROUTE}.get_settings", Settings)
        self.funder(monkeypatch, {"id": 1, "slug": "sbi-foundation", "name": "SBI"})
        async with client_for(funders_api.router) as client:
            response = await client.get("/api/funders/sbi-foundation/brief")
        assert response.status_code == 404


async def _async(value):
    return value

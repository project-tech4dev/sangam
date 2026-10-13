"""The profile routes: one typed facts call per page, then news and the brief by the entity's real slug."""

from app.api.routes import orgs as orgs_api
from app.api.routes import partner_groups as groups_api
from app.api.routes import profiles as profiles_api
from app.schemas.profiles import FunderFacts, OrgFacts

ROUTE = "app.api.routes.profiles"

GROUP = {"key": "o4", "name": "KABIL", "org_slug": "kabil", "lines": [{
    "id": 7, "funder_id": 29, "funder_slug": "axis-bank-foundation", "funder_name": "Axis Bank Foundation",
    "fiscal_year": "FY2024-25", "partner_name": "KABIL", "partner_org_id": 4, "partner_org_slug": "kabil"}]}

ORG = OrgFacts.model_validate({
    "org": {"id": 4, "slug": "kabil", "name": "KABIL", "legal_form": "Society",
            "parent": {"id": 9, "name": "Parent Trust", "slug": "parent-trust"},
            "identifiers": [{"id_type": "pan", "status": "registered", "number_withheld": True}],
            "contacts": [{"id": 3, "name": "Head office", "kind": "other", "email": "a@b.org"}]},
    "places": [{"location_id": 11, "kind": "district", "name": "Dumka", "state": "Jharkhand"}],
    "programs": [{"id": 169, "name": "SLP", "kind": "programme", "metrics": [{"id": 1, "name": "Families", "value": 5}]}],
    "funders": {"groups": [{**GROUP, "key": "29", "name": "Axis Bank Foundation", "funder_slug": "axis-bank-foundation",
                            "org_slug": None}], "total": 1},
    "stories": {"press": 1, "social": 6, "posts_since": "2026-08-04"},
    "research": {"runs": 4, "latest": "2026-10-13", "sources": [{"url": "https://give.do/k", "first_read": "2026-10-01"}]},
    "hidden_contacts": 5,
})

FUNDER = FunderFacts.model_validate({
    "funder": {"id": 29, "slug": "axis-bank-foundation", "name": "Axis Bank Foundation",
               "funder_type": "corporate_foundation", "funding_trend": "Livelihoods first"},
    "partners": {"groups": [GROUP], "total": 48, "in_registry": 1, "next_cursor": "WzIwXQ=="},
    "spend": [{"id": 1, "fiscal_year": "FY2024-25", "amount": 2.3e9}],
    "open_calls": [{"id": 6, "title": "Call 2026"}],
})


def _patch(monkeypatch, *, org=ORG, funder=FUNDER, brief=None):
    calls = {"news": [], "brief": []}

    async def org_facts(pool, owner, slug_or_id):
        return org

    async def funder_facts(pool, owner, slug_or_id):
        return funder

    async def news(kind, slug, pool):
        calls["news"].append((kind, slug))
        return []

    async def brief_link(slug):
        calls["brief"].append(slug)
        if isinstance(brief, Exception):
            raise brief
        return brief

    monkeypatch.setattr(f"{ROUTE}.profile_facts.org_facts", org_facts)
    monkeypatch.setattr(f"{ROUTE}.profile_facts.funder_facts", funder_facts)
    monkeypatch.setattr(f"{ROUTE}._news", news)
    monkeypatch.setattr(f"{ROUTE}.storage.brief_link", brief_link)
    return calls


async def test_org_profile_is_the_typed_facts_plus_news_and_brief(client_for, monkeypatch):
    _patch(monkeypatch)
    async with client_for(profiles_api.router) as client:
        body = (await client.get("/api/orgs/kabil/profile")).json()
    assert body["org"]["parent"]["slug"] == "parent-trust"
    assert body["org"]["identifiers"][0] == {**body["org"]["identifiers"][0], "number_withheld": True, "id_value": None}
    assert body["funders"]["total"] == 1 and body["stories"] == {"press": 1, "social": 6, "posts_since": "2026-08-04"}
    assert body["hidden_contacts"] == 5 and body["research"]["runs"] == 4
    assert body["brief"] is None and body["news"] == []
    # Nothing of the org's private record rides along.
    assert "darpan_id" not in body["org"] and "contact" not in body["org"] and "profile" not in body["org"]


async def test_funder_profile_serves_the_first_partner_page_and_its_sql_total(client_for, monkeypatch):
    _patch(monkeypatch)
    async with client_for(profiles_api.router) as client:
        body = (await client.get("/api/funders/axis-bank-foundation/profile")).json()
    assert body["partners"]["total"] == 48 and body["partners"]["next_cursor"] == "WzIwXQ=="
    assert body["partners"]["groups"][0]["lines"][0]["partner_org_slug"] == "kabil"
    assert body["funder"]["funding_trend"] == "Livelihoods first"


async def test_a_page_asked_for_by_id_reads_news_and_brief_by_the_real_slug(client_for, monkeypatch):
    calls = _patch(monkeypatch)
    async with client_for(profiles_api.router) as client:
        await client.get("/api/orgs/4/profile")
        await client.get("/api/funders/29/profile")
    assert calls["news"] == [("org", "kabil"), ("funder", "axis-bank-foundation")]
    assert calls["brief"] == ["kabil", "axis-bank-foundation"]


async def test_404_comes_from_the_facts(client_for, monkeypatch):
    _patch(monkeypatch, org=None, funder=None)
    async with client_for(profiles_api.router) as client:
        org = await client.get("/api/orgs/nope/profile")
        funder = await client.get("/api/funders/nope/profile")
    assert (org.status_code, funder.status_code) == (404, 404)


async def test_a_brief_storage_failure_leaves_the_page_up(client_for, monkeypatch):
    _patch(monkeypatch, brief=RuntimeError("storage down"))
    async with client_for(profiles_api.router) as client:
        org = await client.get("/api/orgs/kabil/profile")
        funder = await client.get("/api/funders/axis-bank-foundation/profile")
    assert org.status_code == 200 and org.json()["brief"] is None
    assert funder.status_code == 200 and funder.json()["brief"] is None


async def test_a_published_brief_is_linked(client_for, monkeypatch):
    _patch(monkeypatch, brief="https://p/sign?token=t")
    async with client_for(profiles_api.router) as client:
        body = (await client.get("/api/orgs/kabil/profile")).json()
    assert body["brief"]["url"].endswith("token=t")


# --- the brief on its own ------------------------------------------------------

def _org_row(monkeypatch, row):
    async def get_org(pool, slug_or_id):
        return row

    monkeypatch.setattr("app.api.routes.orgs.repo.get_org", get_org)


async def test_org_brief_endpoint_names_the_real_slug(client_for, monkeypatch):
    calls = _patch(monkeypatch, brief="https://p/sign?token=t")
    _org_row(monkeypatch, {"id": 4, "slug": "kabil", "name": "KABIL"})
    async with client_for(orgs_api.router) as client:
        response = await client.get("/api/orgs/4/brief")
    assert response.status_code == 200
    assert response.json() == {"url": "https://p/sign?token=t", "expires_in_seconds": 3600,
                               "slug": "kabil", "name": "KABIL"}
    assert calls["brief"] == ["kabil"]


async def test_org_brief_endpoint_404s_without_a_brief_or_an_org(client_for, monkeypatch):
    _patch(monkeypatch)
    _org_row(monkeypatch, {"id": 4, "slug": "kabil", "name": "KABIL"})
    async with client_for(orgs_api.router) as client:
        assert (await client.get("/api/orgs/kabil/brief")).status_code == 404
    _org_row(monkeypatch, None)
    async with client_for(orgs_api.router) as client:
        assert (await client.get("/api/orgs/nope/brief")).status_code == 404


async def test_brief_endpoint_502s_when_storage_cannot_sign(client_for, monkeypatch):
    from app.integrations.storage import BriefUnreachable

    _patch(monkeypatch, brief=BriefUnreachable("no signature"))
    _org_row(monkeypatch, {"id": 4, "slug": "kabil", "name": "KABIL"})
    async with client_for(orgs_api.router) as client:
        assert (await client.get("/api/orgs/kabil/brief")).status_code == 502


# --- partner groups, page by page ------------------------------------------------

async def test_partner_groups_page_by_group_with_a_sql_total(client_for, monkeypatch):
    seen = []

    async def groups(pool, side, slug_or_id, *, cursor, limit):
        seen.append((side, slug_or_id, cursor, limit))
        return {"groups": [GROUP], "total": 48, "in_registry": 1, "has_amounts": False, "next_cursor": None}

    monkeypatch.setattr("app.api.routes.partner_groups.repo.entity_groups", groups)
    async with client_for(groups_api.router) as client:
        funder = await client.get("/api/funders/axis-bank-foundation/partners", params={"cursor": "WzIwXQ=="})
        org = await client.get("/api/orgs/kabil/funders")
    assert funder.status_code == 200 and funder.json()["total"] == 48
    assert org.status_code == 200
    assert seen == [("funder", "axis-bank-foundation", "WzIwXQ==", 20), ("org", "kabil", None, 20)]


async def test_partner_groups_bad_cursor_is_400_and_unknown_is_404(client_for, monkeypatch):
    async def bad(pool, side, slug_or_id, *, cursor, limit):
        if cursor:
            raise ValueError("bad cursor")

    monkeypatch.setattr("app.api.routes.partner_groups.repo.entity_groups", bad)
    async with client_for(groups_api.router) as client:
        assert (await client.get("/api/funders/x/partners", params={"cursor": "zz"})).status_code == 400
        assert (await client.get("/api/funders/nope/partners")).status_code == 404

"""Org members and RFP routes: repository results and refusals mapped to HTTP."""

from __future__ import annotations

import pytest
from psycopg import errors

from app.api.routes import org_members as members_api
from app.api.routes import rfps as rfps_api

USER = "00000000-0000-0000-0000-0000000000aa"
MEMBER = {"user_id": USER, "display_name": "Asha", "email": "asha@example.org", "role": "member"}
RFP = {"id": 3, "title": "Water call", "funder_id": 7, "funder_name": "Tata Trusts", "status": "open"}


@pytest.fixture
def members(monkeypatch):
    calls: list[tuple] = []

    async def list_members(pool, org_id):
        calls.append(("list", org_id))
        return [MEMBER]

    monkeypatch.setattr(members_api.repo, "list_members", list_members)
    return calls


async def test_list_members(client_for, members):
    async with client_for(members_api.router) as client:
        r = await client.get("/api/orgs/4/members")
    assert r.status_code == 200 and r.json()[0]["email"] == "asha@example.org"
    assert members == [("list", 4)]


async def test_add_set_and_remove_return_the_list(client_for, members, monkeypatch):
    seen: list[tuple] = []

    async def add(pool, org_id, email, role):
        seen.append(("add", org_id, email, role))

    async def set_role(pool, org_id, user_id, role):
        seen.append(("role", org_id, str(user_id), role))

    async def remove(pool, org_id, user_id):
        seen.append(("remove", org_id, str(user_id)))

    monkeypatch.setattr(members_api.repo, "add_member", add)
    monkeypatch.setattr(members_api.repo, "set_role", set_role)
    monkeypatch.setattr(members_api.repo, "remove_member", remove)
    async with client_for(members_api.router) as client:
        r1 = await client.post("/api/orgs/4/members", json={"email": "ravi@example.org"})
        r2 = await client.patch(f"/api/orgs/4/members/{USER}", json={"role": "admin"})
        r3 = await client.delete(f"/api/orgs/4/members/{USER}")
    assert (r1.status_code, r2.status_code, r3.status_code) == (201, 200, 200)
    assert seen == [("add", 4, "ravi@example.org", "member"), ("role", 4, USER, "admin"), ("remove", 4, USER)]


@pytest.mark.parametrize("exc, code, detail", [
    (errors.InsufficientPrivilege("only admins may add"), 403, "only admins may add"),
    (errors.NoDataFound("no user with that email"), 404, "no user with that email"),
    (errors.RaiseException("the last admin cannot leave"), 400, "the last admin cannot leave"),
    (errors.UniqueViolation("dup"), 409, "That person is already an admin or member of another organisation."),
])
async def test_a_refusal_becomes_http_with_its_message(client_for, members, monkeypatch, exc, code, detail):
    async def add(pool, org_id, email, role):
        raise exc

    monkeypatch.setattr(members_api.repo, "add_member", add)
    async with client_for(members_api.router) as client:
        r = await client.post("/api/orgs/4/members", json={"email": "ravi@example.org", "role": "admin"})
    assert r.status_code == code and r.json()["detail"] == detail


async def test_an_unknown_role_is_422(client_for, members):
    async with client_for(members_api.router) as client:
        r = await client.patch(f"/api/orgs/4/members/{USER}", json={"role": "owner"})
    assert r.status_code == 422


async def test_list_rfps_passes_filters_and_pages(client_for, monkeypatch):
    seen: dict = {}

    async def list_rfps(pool, **kwargs):
        seen.update(kwargs)
        return [RFP], 1

    monkeypatch.setattr(rfps_api.repo, "list_rfps", list_rfps)
    async with client_for(rfps_api.router) as client:
        r = await client.get("/api/rfps", params={"status": "open", "deadline_before": "2026-12-31", "tag": "water"})
    body = r.json()
    assert r.status_code == 200 and body["total"] == 1 and body["items"][0]["title"] == "Water call"
    assert seen["deadline_before"] == "2026-12-31" and seen["status"] == "open" and seen["tag"] == "water"


async def test_list_rfps_without_a_deadline(client_for, monkeypatch):
    async def list_rfps(pool, **kwargs):
        assert kwargs["deadline_before"] is None
        return [], 0

    monkeypatch.setattr(rfps_api.repo, "list_rfps", list_rfps)
    async with client_for(rfps_api.router) as client:
        assert (await client.get("/api/rfps")).json()["items"] == []


async def test_feed_found_and_missing(client_for, monkeypatch):
    async def feed(pool, org):
        if org not in ("kabil", None):
            return None
        return {"id": 9, "slug": "kabil", "name": "KABIL", "can_act": True, "domains": ["water"], "last_pulled": None,
                "items": [{"rfp_id": 3, "title": "Water call", "places": ["Assam"]}]}

    monkeypatch.setattr(rfps_api.repo, "feed", feed)
    async with client_for(rfps_api.router) as client:
        ok = await client.get("/api/rfps/feed", params={"org": "kabil"})
        missing = await client.get("/api/rfps/feed", params={"org": "nobody"})
        own = await client.get("/api/rfps/feed")
    assert ok.status_code == 200 and ok.json()["items"][0]["places"] == ["Assam"] and ok.json()["can_act"]
    assert missing.status_code == 404
    assert own.status_code == 200 and own.json()["org_slug"] == "kabil"


async def test_get_rfp_and_its_matches(client_for, monkeypatch):
    async def get_rfp(pool, rfp_id):
        return RFP if rfp_id == 3 else None

    async def list_matches(pool, rfp_id):
        return [{"rfp_id": 3, "org_id": 9, "org_name": "KABIL", "status": "flagged"}]

    monkeypatch.setattr(rfps_api.repo, "get_rfp", get_rfp)
    monkeypatch.setattr(rfps_api.repo, "list_matches", list_matches)
    async with client_for(rfps_api.router) as client:
        one = await client.get("/api/rfps/3")
        none = await client.get("/api/rfps/4")
        matches = await client.get("/api/rfps/3/matches")
        no_matches = await client.get("/api/rfps/4/matches")
    assert one.json()["funder_name"] == "Tata Trusts" and none.status_code == 404
    assert matches.json()[0]["org_name"] == "KABIL" and no_matches.status_code == 404

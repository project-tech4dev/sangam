"""Saving a Funder Match run: the rows a run writes, who the route lets run one, and the chat gate."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import httpx

from app.agent.tools import matching_tools
from app.api.routes import funder_matches
from app.core.security import ANONYMOUS, CurrentUser, chat_user_id, get_principal
from app.matching import service
from app.matching.match import match
from app.matching.rules import FunderProfile, Location, OrgProfile, Places, Program
from app.repositories import funder_matches as repo
from app.repositories import matching
from tests.conftest import make_app

PLACES = Places([Location(1, "country", "India", None), Location(2, "state", "Assam", 1),
                 Location(3, "district", "Udalguri", 2), Location(4, "state", "Bihar", 1)])
ORG = OrgProfile(id=9, name="KABIL", location_ids={3}, sector_tags={"livelihoods"},
                 programs=[Program(12, "Women's collectives", frozenset({"livelihoods"}))])
SHARED = FunderProfile(id=7, name="HDFC Bank Parivartan", funder_type="corporate_csr", section_135_bound=True,
                       location_ids={3},
                       sector_tags={"livelihoods"})
NOTHING = FunderProfile(id=8, name="Infosys Foundation", funder_type="corporate_csr", section_135_bound=True,
                        location_ids={4},
                        sector_tags={"health"})
MEMBER = CurrentUser(id=uuid4(), is_staff=False, auth_user_id=uuid4())


class TestRows:
    def test_a_scored_row_carries_the_score_card_and_all_seven_criteria(self):
        [row] = service.rows([match(ORG, SHARED, PLACES)])
        assert row["score"] == row["detail"]["score"]["of_100"]
        assert [c["code"] for c in row["detail"]["criteria"]][:2] == ["theme", "geography"]
        assert len(row["detail"]["criteria"]) == 7
        assert {r["kind"] for r in row["card"]["reasons"]} <= {"fit", "gap"}

    def test_an_unscored_row_has_one_card_line_and_no_criteria(self):
        [row] = service.rows([match(ORG, NOTHING, PLACES)])
        assert row["score"] is None
        assert row["card"] == {"reasons": [{"kind": "gap", "criterion": "overlap",
                                            "text": "No shared place or theme recorded"}]}
        assert row["detail"]["criteria"] == [] and row["detail"]["improve"] == []

    def test_the_rows_are_json(self):
        json.dumps(service.rows([match(ORG, SHARED, PLACES), match(ORG, NOTHING, PLACES)]))


async def _post(monkeypatch, found, principal=None):
    async def find_org(pool, slug):
        return found

    async def run_and_save(reader, writer, org_id, run_by):
        return {"run_id": UUID(int=1), "run_at": "2026-10-10T02:30:00Z", "org_id": org_id,
                "rubric_version": "match-v1", "funders_checked": 43,
                "tiers": {"strong": 1, "medium": 2, "weak": 30, "not_scored": 10}}

    monkeypatch.setattr(repo, "find_org", find_org)
    monkeypatch.setattr(service, "run_and_save", run_and_save)
    app = make_app(funder_matches.router)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/funder-matches/runs?org=kabil")


class TestRunRoute:
    async def test_a_steward_admin_or_staff_run_is_saved(self, monkeypatch):
        r = await _post(monkeypatch, {"id": 9, "slug": "kabil", "name": "KABIL", "may_run": True})
        assert r.status_code == 201
        assert r.json()["funders_checked"] == 43

    async def test_a_member_is_refused(self, monkeypatch):
        r = await _post(monkeypatch, {"id": 9, "slug": "kabil", "name": "KABIL", "may_run": False},
                        MEMBER)
        assert r.status_code == 403

    async def test_an_org_the_caller_cannot_see_is_not_found(self, monkeypatch):
        assert (await _post(monkeypatch, None)).status_code == 404

    async def test_signed_out_is_unauthorised(self, monkeypatch):
        assert (await _post(monkeypatch, None, ANONYMOUS)).status_code == 401


class TestCompareFitGate:
    async def test_a_member_is_refused_before_anything_is_read(self, monkeypatch):
        async def may_run(pool, user_id, org_id):
            return False

        async def load(*a, **kw):
            raise AssertionError("loaded data for a caller who may not run a match")

        monkeypatch.setattr(matching_tools, "get_pool", lambda: None)
        monkeypatch.setattr(matching, "may_run", may_run)
        monkeypatch.setattr(matching, "load", load)
        token = chat_user_id.set(MEMBER.id)
        try:
            out = await matching_tools.compare_fit.ainvoke({"org_id": 9})
        finally:
            chat_user_id.reset(token)
        assert out.startswith("compare_fit refused")

    async def test_no_chat_user_is_refused(self):
        assert not await matching.may_run(None, None, 9)


KABIL = {"id": 9, "slug": "kabil", "name": "KABIL", "may_read": True, "may_run": False}
RUN = {"run_id": UUID(int=2), "run_at": "2026-10-10T02:30:00Z", "rubric_version": "match-v1",
       "funders_checked": 2, "earlier_runs": 1, "prev_run_id": UUID(int=1)}


def _row(id_, score, prev=None):
    return {"id": id_, "score": score, "prev_score": prev, "card": {"reasons": []}, "funder_id": id_,
            "funder_slug": f"f{id_}", "funder_name": f"F{id_}", "funder_type": None}


async def _get(monkeypatch, found, run=None, rows=()):
    async def find_org(pool, slug):
        return found

    async def latest_run(pool, org_id):
        return run

    async def list_matches(pool, run_id, prev_run_id):
        return list(rows)

    monkeypatch.setattr(repo, "find_org", find_org)
    monkeypatch.setattr(repo, "latest_run", latest_run)
    monkeypatch.setattr(repo, "list_matches", list_matches)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(funder_matches.router)),
                                 base_url="http://test") as client:
        return await client.get("/api/funder-matches?org=kabil")


class TestListRoute:
    async def test_an_org_never_run_has_no_run_and_no_matches(self, monkeypatch):
        body = (await _get(monkeypatch, KABIL)).json()
        assert body["run"] is None and body["matches"] == [] and body["may_run"] is False

    async def test_matches_keep_the_repository_order_with_tiers_and_the_previous_score(self, monkeypatch):
        body = (await _get(monkeypatch, KABIL, RUN, [_row(7, 80, 73), _row(8, None)])).json()
        assert [(m["score"], m["tier"], m["prev_score"]) for m in body["matches"]] == [
            (80, "strong", 73), (None, "not_scored", None)]
        assert body["counts"] == {"strong": 1, "medium": 0, "weak": 0, "not_scored": 1}
        assert body["run"]["earlier_runs"] == 1

    async def test_an_org_the_caller_cannot_read_is_not_found(self, monkeypatch):
        assert (await _get(monkeypatch, None)).status_code == 404
        assert (await _get(monkeypatch, {**KABIL, "may_read": False})).status_code == 404

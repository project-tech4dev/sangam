"""The matching and profile tools: resolve, one service call, render, and never raise."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.agent.tools import match_tools, profile_tools
from app.matching import service
from app.matching.models import Ambiguous, FunderProfile, FunderRef, OrgRef, Resolved, Shortlist


class _Pool:
    @asynccontextmanager
    async def connection(self):
        yield "conn"


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    for module in (match_tools, profile_tools):
        monkeypatch.setattr(module, "get_pool", lambda: _Pool())


def resolves_to(monkeypatch, **by_text):
    async def resolve(conn, kind, text):
        hit = by_text.get(text)
        return Resolved(kind=kind, id=hit, name=text.upper()) if hit else Ambiguous(kind=kind, text=text, candidates=[
            Resolved(kind=kind, id=40, name="Assam Trust A"), Resolved(kind=kind, id=41, name="Assam Trust B")])
    monkeypatch.setattr(service, "resolve", resolve)


def never(*_a, **_k):
    raise AssertionError("a judgement ran on an unresolved name")


class TestMatchFunders:
    async def test_an_ambiguous_org_returns_candidates_and_judges_nothing(self, monkeypatch):
        resolves_to(monkeypatch)
        monkeypatch.setattr(service, "shortlist", never)
        out = await match_tools.match_funders.ainvoke({"org": "assam trust"})
        assert "Assam Trust A [org:40]" in out and "do not pick" in out

    async def test_a_resolved_org_is_shortlisted_and_rendered(self, monkeypatch):
        resolves_to(monkeypatch, kabil=9)
        seen = {}

        async def shortlist(conn, org_id, *, limit):
            seen.update(org_id=org_id, limit=limit)
            return Shortlist(criteria_version=1, criteria_hash="abcdef12", org=OrgRef(id=9, name="KABIL"),
                             ranked=[], not_enough_recorded=[], did_not_pass=[], total_funders=0, offset=0,
                             limit=limit)
        monkeypatch.setattr(service, "shortlist", shortlist)
        out = await match_tools.match_funders.ainvoke({"org": "kabil", "limit": 500})
        assert seen == {"org_id": 9, "limit": 50} and "criteria v1" in out

    async def test_a_service_error_is_a_string(self, monkeypatch):
        resolves_to(monkeypatch, kabil=9)

        async def boom(*_a, **_k):
            raise LookupError("org 9 not found")
        monkeypatch.setattr(service, "shortlist", boom)
        assert await match_tools.match_funders.ainvoke({"org": "kabil"}) == "match_funders failed: org 9 not found"


class TestExplainMatch:
    async def test_four_funders_is_refused(self, monkeypatch):
        resolves_to(monkeypatch, kabil=9, a=1, b=2, c=3, d=4)
        monkeypatch.setattr(service, "assess_many", never)
        out = await match_tools.explain_match.ainvoke({"org": "kabil", "funders": ["a", "b", "c", "d"]})
        assert out.startswith("explain_match failed:") and "three" in out

    async def test_an_ambiguous_funder_asks(self, monkeypatch):
        resolves_to(monkeypatch, kabil=9, a=1)
        monkeypatch.setattr(service, "assess_many", never)
        out = await match_tools.explain_match.ainvoke({"org": "kabil", "funders": ["a", "assam trust"]})
        assert "[funder:40]" in out


class TestProfiles:
    async def test_get_funder_renders_the_profile(self, monkeypatch):
        resolves_to(monkeypatch, hdfc=2)

        async def profile(conn, kind, ref_id):
            assert (kind, ref_id) == ("funder", 2)
            return FunderProfile(funder=FunderRef(id=2, name="HDFC Bank"))
        monkeypatch.setattr(service, "profile", profile)
        out = await profile_tools.get_funder.ainvoke({"funder": "hdfc"})
        assert "HDFC Bank [funder:2]" in out and "no eligibility bars recorded" in out

    async def test_find_funders_passes_its_filters_through(self, monkeypatch):
        seen = {}

        async def find(conn, **kw):
            seen.update(kw)
            raise ValueError("no district or state named 'Atlantis'; near: nothing close")
        monkeypatch.setattr(service, "find_funders", find)
        out = await profile_tools.find_funders.ainvoke({"places": ["Atlantis"], "themes": ["livelihoods"]})
        assert out.startswith("find_funders failed: no district or state named")
        assert seen["places"] == ["Atlantis"] and seen["themes"] == ["livelihoods"] and seen["funder_types"] == []

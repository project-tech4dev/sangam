"""compare_fit: one call, profiles to a scored, sorted shortlist. The repository is faked."""

from __future__ import annotations

import json

from app.agent.rules import FunderProfile, Location, OrgProfile, Places
from app.agent.tools import matching_tools

PLACES = Places([
    Location(1, "country", "India", None),
    Location(10, "state", "Assam", 1),
    Location(11, "state", "Bihar", 1),
    Location(100, "district", "Udalguri", 10),
    Location(110, "district", "Patna", 11),
])
KABIL = OrgProfile(id=9, name="KABIL", location_ids={100}, sector_tags={"agriculture"}, identifiers={"12a": [True]})
NEAR = FunderProfile(7, "Axis Bank Foundation", "corporate_csr", True, location_ids={100})
STATE = FunderProfile(8, "Azim Premji Foundation", "private_foundation", False, location_ids={10})
FAR = FunderProfile(4, "ONGC", "corporate_csr", True, location_ids={110}, sector_tags={"energy"})
BLANK = FunderProfile(2, "HDFC Bank Limited", None, None)


def _fake(funders):
    async def load(pool, org_id, funder_ids, *, timeout_ms):
        if org_id != 9:
            return None, [], PLACES
        return KABIL, [f for f in funders if funder_ids is None or f.id in funder_ids], PLACES
    return load


async def _call(monkeypatch, funders, **args) -> str:
    monkeypatch.setattr(matching_tools.matching, "load", _fake(funders))
    monkeypatch.setattr(matching_tools, "get_pool", lambda: None)
    return await matching_tools.compare_fit.ainvoke(args)


async def test_a_shortlist_assesses_what_shares_something_and_counts_the_rest(monkeypatch):
    out = json.loads(await _call(monkeypatch, [NEAR, STATE, FAR, BLANK], org_id=9))
    assert [a["funder_id"] for a in out["assessed"]] == sorted(
        [7, 8], key=lambda i: next(a["rank_key"] for a in out["assessed"] if a["funder_id"] == i)
    )
    assert out["not_assessed"]["nothing_in_common_recorded"] == 1
    assert out["not_assessed"]["nothing_recorded"] == ["HDFC Bank Limited [funder:2]"]


async def test_entries_are_in_rank_key_order_with_the_computed_verdict(monkeypatch):
    out = json.loads(await _call(monkeypatch, [NEAR, STATE], org_id=9))
    keys = [a["rank_key"] for a in out["assessed"]]
    assert keys == sorted(keys)
    for a in out["assessed"]:
        assert {"gate", "gate_reasons", "score", "coverage", "rank_key", "cite"} <= set(a)


async def test_readiness_is_listed_once_not_per_funder(monkeypatch):
    out = json.loads(await _call(monkeypatch, [NEAR, STATE], org_id=9))
    assert len(out["readiness"]) == 12
    assert all(c["code"] in {"area", "theme", "programme", "funder_bar"} for a in out["assessed"] for c in a["checks"])


async def test_named_funders_are_assessed_even_with_nothing_shared(monkeypatch):
    out = json.loads(await _call(monkeypatch, [NEAR, FAR], org_id=9, funder_ids=[4]))
    assert [a["funder_id"] for a in out["assessed"]] == [4]


async def test_an_unknown_id_is_an_error_string_not_a_raise(monkeypatch):
    assert (await _call(monkeypatch, [NEAR], org_id=1)).startswith("compare_fit failed")
    assert "no funder with id 99" in await _call(monkeypatch, [NEAR], org_id=9, funder_ids=[99])


async def test_a_repository_error_is_returned(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("pool closed")
    monkeypatch.setattr(matching_tools.matching, "load", boom)
    monkeypatch.setattr(matching_tools, "get_pool", lambda: None)
    assert await matching_tools.compare_fit.ainvoke({"org_id": 9}) == "compare_fit failed: pool closed"

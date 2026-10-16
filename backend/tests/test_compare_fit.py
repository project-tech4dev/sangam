"""compare_fit's reply: a shortlist that fits in the conversation, and full detail on request."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.tools import matching_tools
from app.matching import rubric
from app.matching.assessment import Criterion, Match, Reason

# deepagents evicts a tool reply over 20k tokens (4 chars each); the shortlist's budget is 15k.
SHORTLIST_BUDGET_CHARS = 60_000
LONG = "x" * 220


def _match(funder_id: int, share: float, *, note: str = LONG) -> Match:
    criteria = [
        Criterion(code=code, points=round(top * share), note=note, cites=["[org:8]", f"[funder:{funder_id}]"])
        for code, (_, top) in rubric.CRITERIA.items()
    ]
    return Match(
        org_id=8,
        funder_id=funder_id,
        funder_name=f"Funder {funder_id}",
        funder_type="corporate_csr",
        criteria=criteria,
        card=[Reason(kind="fit", criterion="theme", text=f"fit line {LONG}"),
              Reason(kind="gap", criterion="eligibility", text=f"gap {funder_id}")],
        summary=f"summary {LONG}",
        not_judged=[f"bar {LONG}"] * 3,
        improve=[f"action {LONG}"] * 4,
    )


@pytest.fixture
def funders(monkeypatch):
    """compare() over prepared matches: share of each criterion's points, by funder id."""
    def use(shares: dict[int, float | None]):
        def fake_match(org, funder, places):
            share = shares[funder.id]
            if share is None:
                m = _match(funder.id, 0.0)
                return m.model_copy(update={"criteria": [c.model_copy(update={"points": None}) for c in m.criteria]})
            return _match(funder.id, share)

        monkeypatch.setattr(matching_tools, "match", fake_match)
        monkeypatch.setattr(matching_tools, "has_places_or_themes", lambda f: f.id % 2 == 0)
        return [SimpleNamespace(id=i) for i in shares]

    return use


ORG = SimpleNamespace(id=8, name="Better Life Foundation")


def _reply(funder_list, *, shortlist):
    return matching_tools.render(matching_tools.compare(ORG, funder_list, None, shortlist=shortlist), shortlist=shortlist)


def test_worst_case_shortlist_stays_under_the_budget(funders):
    reply = _reply(funders({i: 1.0 if i % 2 else 0.6 for i in range(1, 38)}), shortlist=True)
    assert len(reply) < SHORTLIST_BUDGET_CHARS
    # Pages cleanly when it is ever evicted: one fact per line, not one JSON line.
    assert reply.count("\n") > 50


def test_top_fits_in_full_the_rest_one_line_each(funders):
    reply = _reply(funders({i: 1.0 for i in range(1, 13)} | {20: 0.2}), shortlist=True)
    assert reply.count("to raise the score:") == matching_tools.FULL_DETAIL_MAX * 4
    assert "summary:" not in reply
    one_liners = [line for line in reply.splitlines() if line.startswith("- Funder")]
    assert len(one_liners) == 3
    assert "- Funder 20 [funder:20] · corporate_csr · 20/100 · weak · ! gap 20" in one_liners


def test_named_funders_carry_every_field(funders):
    reply = _reply(funders({3: 0.2, 4: 1.0}), shortlist=False)
    assert reply.count("summary:") == 2
    assert reply.count("   - ") == 2 * len(rubric.CRITERIA)
    assert "not judged:" in reply and "[funder:3]" in reply


def test_unknown_criteria_are_counted_once_and_never_scored(funders):
    reply = _reply(funders({2: None, 4: 0.6}), shortlist=False)
    assert "unknown across the 1 scored" not in reply  # a funder with nothing judged is not scored
    assert "not scored" in reply
    assert "unknown unknown" not in reply


def test_not_scored_keeps_unknown_apart_from_nothing_shared(funders):
    reply = _reply(funders({1: None, 2: None, 4: 0.6}), shortlist=True)
    assert "not scored, nothing in common recorded: Funder 2 [funder:2]" in reply
    assert "not scored, the funder has nothing recorded (unknown, not a poor fit): Funder 1 [funder:1]" in reply
    assert "scored 1: 1 medium · not scored 2" in reply

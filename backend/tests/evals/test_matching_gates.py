"""The matching eval gates, tested with no model calls and no database."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import ToolMessage

from tests.evals.harness import CaseResult, assessments_in, compare_calls, score


def _a(funder_id: int, gate: str, rank_key: str) -> dict:
    return {"funder_id": funder_id, "gate": gate, "rank_key": rank_key}


def _score(case: dict, answer: str, assessments: list[dict]) -> list[str]:
    result = CaseResult(case_id="t", answer=answer, assessments=assessments)
    return score(case, result, gold_rows=None, agent_rows=None).failures


def test_assessments_are_read_from_compare_fit_messages():
    reply = json.dumps({"assessed": [_a(2, "pass", "0-000")]})
    messages = [
        ToolMessage(content=reply, name="compare_fit", tool_call_id="1"),
        ToolMessage(content="compare_fit failed: x", name="compare_fit", tool_call_id="2"),
        ToolMessage(content=reply, name="db_query", tool_call_id="3"),
    ]
    assert assessments_in(messages) == [_a(2, "pass", "0-000")]
    assert compare_calls(messages) == 2


def test_too_few_assessments_fail():
    assert _score({"min_assessments": 2}, "", [_a(2, "pass", "0")])


ORDERED = {"ordered_by_rank_key": True}
ORDERED_REPLIES = (_a(2, "pass", "0-010"), _a(7, "unverified", "1-020"), _a(5, "pass", "0-005"))
REMOVED = {"removed_after_shortlist": True}
REMOVED_REPLIES = (_a(2, "pass", "0-010"), _a(9, "fail", "2-050"))


class TestOrderedByRankKey:
    def test_the_answer_in_key_order_passes(self):
        answer = "[funder:5] first, then [funder:2], then [funder:7]"
        assert not _score(ORDERED, answer, list(ORDERED_REPLIES))

    def test_out_of_order_fails(self):
        answer = "[funder:2] first, then [funder:5], then [funder:7]"
        assert _score(ORDERED, answer, list(ORDERED_REPLIES))

    def test_a_funder_the_answer_omits_is_not_held_against_it(self):
        assert not _score(ORDERED, "[funder:5] then [funder:7]", list(ORDERED_REPLIES))


class TestRemovedAfterShortlist:
    def test_a_failed_funder_under_removed_passes(self):
        assert not _score(REMOVED, "Eligible: [funder:2]\nRemoved: [funder:9]", list(REMOVED_REPLIES))

    def test_a_failed_funder_listed_before_removed_fails(self):
        assert _score(REMOVED, "Eligible: [funder:9] [funder:2]\nRemoved: none", list(REMOVED_REPLIES))


ONCE = {"compare_fit_once": True}


@pytest.mark.parametrize(("calls", "fails"), [(0, True), (1, False), (2, True)])
def test_compare_fit_runs_exactly_once(calls, fails):
    result = CaseResult(case_id="t", compare_calls=calls)
    assert bool(score(ONCE, result, gold_rows=None, agent_rows=None).failures) is fails

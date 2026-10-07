"""The matching eval gates, tested with no model calls and no database."""

from __future__ import annotations

import json

from langchain_core.messages import ToolMessage

from tests.evals.harness import CaseResult, assessments_in, score, task_order


def _a(funder_id: int, gate: str, rank_key: str) -> dict:
    return {"funder_id": funder_id, "gate": gate, "rank_key": rank_key}


def _score(case: dict, answer: str, assessments: list[dict]) -> list[str]:
    result = CaseResult(case_id="t", answer=answer, assessments=assessments)
    return score(case, result, gold_rows=None, agent_rows=None).failures


def test_assessor_replies_are_read_from_task_messages():
    reply = json.dumps(_a(2, "pass", "0-000"))
    messages = [
        ToolMessage(content=reply, name="task", tool_call_id="1"),
        ToolMessage(content="KABIL works in Assam", name="task", tool_call_id="2"),
        ToolMessage(content=reply, name="db_query", tool_call_id="3"),
    ]
    assert assessments_in(messages) == [_a(2, "pass", "0-000")]


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


READY = {"readiness_before_pairs": True}


def _ready(order: list[str], assessments: list[dict] | None = None) -> list[str]:
    result = CaseResult(case_id="t", task_order=order, assessments=assessments or [])
    return score(READY, result, gold_rows=None, agent_rows=None).failures


class TestReadinessBeforePairs:
    def test_the_task_order_is_read_from_task_messages(self):
        readiness = json.dumps({"org_id": 9, "org_name": "KABIL", "checks": []})
        messages = [
            ToolMessage(content=readiness, name="task", tool_call_id="1"),
            ToolMessage(content=json.dumps(_a(2, "pass", "0")), name="task", tool_call_id="2"),
            ToolMessage(content="funder-assessor failed: x", name="task", tool_call_id="3"),
        ]
        assert task_order(messages) == ["readiness:9", "assessment:2", "other"]

    def test_readiness_then_a_wave_passes(self):
        assert not _ready(["readiness:9", "assessment:2", "assessment:7"])

    def test_no_readiness_fails(self):
        assert _ready(["assessment:2"])

    def test_a_pair_before_readiness_fails(self):
        assert _ready(["assessment:2", "readiness:9"])

    def test_readiness_twice_for_one_org_fails(self):
        assert _ready(["readiness:9", "assessment:2", "readiness:9"])

    def test_org_checks_that_differ_between_funders_fail(self):
        met = {**_a(2, "pass", "0"), "checks": [{"code": "reg_12a", "outcome": "met"}]}
        unknown = {**_a(7, "pass", "1"), "checks": [{"code": "reg_12a", "outcome": "unknown"}]}
        assert _ready(["readiness:9", "assessment:2", "assessment:7"], [met, unknown])

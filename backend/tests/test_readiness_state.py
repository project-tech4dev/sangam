"""Readiness is judged once and reaches every funder-assessor through graph state, never through a model."""

from __future__ import annotations

import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.agent.assessment import FunderAssessment, PairAssessment, ReadinessAssessment
from app.agent.state import merge_readiness, merged_reply, readiness_update
from tests.test_assessment import _pair, _readiness


def _stored(org_id: int = 126) -> dict:
    state = {"structured_response": ReadinessAssessment.model_validate(_readiness(org_id=org_id))}
    return readiness_update(state)["org_readiness"]


class TestTheReducer:
    def test_two_organisations_are_both_kept(self):
        assert set(merge_readiness(_stored(1), _stored(2))) == {"1", "2"}

    def test_a_wave_returning_the_same_entry_is_harmless(self):
        entry = _stored()
        merged = None
        for _ in range(8):
            merged = merge_readiness(merged, entry)
        assert merged == entry


class TestRecordReadiness:
    def test_it_files_the_reply_under_its_org(self):
        entry = _stored()["126"]
        assert entry["assessment"]["org_name"] == "KABIL"
        assert entry["assessed_at"]

    def test_anything_else_is_left_alone(self):
        assert readiness_update({"structured_response": None}) is None


class TestMergeWithReadiness:
    def test_it_replaces_the_pair_with_a_scored_verdict(self):
        state = {"structured_response": PairAssessment.model_validate(_pair()), "org_readiness": _stored()}
        reply = merged_reply(state)["structured_response"]
        assert isinstance(reply, FunderAssessment)
        assert json.loads(reply.model_dump_json())["gate"] == "unverified"

    def test_without_readiness_it_says_to_run_it_first_never_a_verdict(self):
        reply = merged_reply({"structured_response": PairAssessment.model_validate(_pair())})["structured_response"]
        assert isinstance(reply, str)
        assert "org-readiness has not run for org 126" in reply

    def test_readiness_for_another_org_is_not_used(self):
        state = {"structured_response": PairAssessment.model_validate(_pair()), "org_readiness": _stored(5)}
        assert "has not run for org 126" in merged_reply(state)["structured_response"]


class _Scripted(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _task(subagent: str, call_id: str) -> dict:
    return {"name": "task", "args": {"description": "KABIL (org_id 126)", "subagent_type": subagent},
            "id": call_id, "type": "tool_call"}


def _graph(supervisor_turns: list[AIMessage], funders: tuple[int, ...]):
    from deepagents import create_deep_agent
    from langchain.agents.structured_output import ToolStrategy
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent.state import AskState, merge_with_readiness, record_readiness

    supervisor = _Scripted(messages=iter(supervisor_turns))
    readiness_model = _Scripted(messages=iter([_call("ReadinessAssessment", _readiness(), "r1")]))
    pair_model = _Scripted(messages=iter(
        [_call("PairAssessment", _pair(funder_id=f, funder_name=f"Funder {f}"), f"p{f}") for f in funders]
    ))
    return create_deep_agent(
        model=supervisor,
        tools=[],
        state_schema=AskState,
        subagents=[
            {"name": "org-readiness", "description": "r", "system_prompt": "r", "tools": [],
             "model": readiness_model, "response_format": ToolStrategy(ReadinessAssessment),
             "middleware": [record_readiness]},
            {"name": "funder-assessor", "description": "f", "system_prompt": "f", "tools": [],
             "model": pair_model, "response_format": ToolStrategy(PairAssessment),
             "middleware": [merge_with_readiness]},
        ],
        checkpointer=InMemorySaver(),
    )


def test_readiness_reaches_a_whole_wave_through_state():
    """Pins the deepagents behaviour this design rests on: an isolated subagent's state update flows back
    to the parent, and subagents launched later inherit it. A library upgrade that breaks this fails here."""
    funders = (2, 7, 9)
    graph = _graph([
        AIMessage(content="", tool_calls=[_task("org-readiness", "r")]),
        AIMessage(content="", tool_calls=[_task("funder-assessor", f"f{f}") for f in funders]),
        AIMessage(content="done"),
    ], funders)

    out = graph.invoke({"messages": [("user", "Which funders can KABIL apply to?")]},
                       {"configurable": {"thread_id": "t"}})

    assert set(out["org_readiness"]) == {"126"}
    replies = [json.loads(m.content) for m in out["messages"] if m.type == "tool" and "rank_key" in m.content]
    assert sorted(r["funder_id"] for r in replies) == list(funders)
    org_sides = [[c for c in r["checks"] if c["code"] == "reg_12a"] for r in replies]
    assert all(side == org_sides[0] for side in org_sides)


def test_a_pair_without_readiness_is_an_error_the_supervisor_reads_not_a_crash():
    # deepagents json.dumps a non-model structured_response, so the string reaches the supervisor.
    graph = _graph([
        AIMessage(content="", tool_calls=[_task("funder-assessor", "f2")]),
        AIMessage(content="done"),
    ], (2,))

    out = graph.invoke({"messages": [("user", "How does KABIL fit HDFC?")]}, {"configurable": {"thread_id": "t"}})

    replies = [m.content for m in out["messages"] if m.type == "tool"]
    assert any("org-readiness has not run for org 126" in r for r in replies)
    assert not any("rank_key" in r for r in replies)

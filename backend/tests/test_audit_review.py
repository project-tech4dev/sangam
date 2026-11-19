"""scripts/audit_review.py: rebuilding past turns and pairing them with their traces, without Langfuse or a DB."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

_PATH = pathlib.Path(__file__).parents[2] / "scripts" / "audit_review.py"
_spec = importlib.util.spec_from_file_location("audit_review", _PATH)
review = importlib.util.module_from_spec(_spec)
sys.modules["audit_review"] = review
_spec.loader.exec_module(review)


def chat():
    return [
        HumanMessage("what does axis bank foundation do?"),
        ToolMessage("1 row(s).\n[activity:1] Udalguri", name="db_query", tool_call_id="1"),
        AIMessage("It funded KABIL [activity:1]."),
        HumanMessage("  who works in udalguri? "),
        AIMessage("KABIL [org:1]."),
        HumanMessage("what does axis bank foundation do?"),
        AIMessage("Asked again: livelihoods."),
    ]


def trace(trace_id, question, at):
    return {"traceId": trace_id, "input": question, "startTime": f"2026-11-19T21:{at}:00Z"}


def test_each_turn_is_the_chat_up_to_its_answer():
    messages = chat()
    [(q1, p1), (q2, p2), (q3, p3)] = review.turns(messages)
    assert (q1, q2, q3) == ("what does axis bank foundation do?", "who works in udalguri?",
                            "what does axis bank foundation do?")
    assert p1 == messages[:3] and p2 == messages[:5] and p3 == messages
    assert review.turns([]) == []


def test_traces_pair_with_their_turn_in_order_even_when_a_question_repeats():
    turns = review.turns(chat())
    traces = [trace("c", "what does axis bank foundation do?", "58"), trace("a", "what does axis bank foundation do?", "51"),
              trace("b", "who works in udalguri?", "54")]
    pairs = review.match(traces, turns)
    assert [(trace_id, len(prefix)) for trace_id, prefix in pairs] == [("a", 3), ("b", 5), ("c", 7)]


def test_a_trace_with_no_matching_turn_is_left_out():
    """A pruned or edited chat: score nothing rather than the wrong turn."""
    pairs = review.match([trace("x", "a question nobody asked here", "50")], review.turns(chat()))
    assert pairs == []

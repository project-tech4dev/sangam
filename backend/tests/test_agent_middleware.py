"""Clearing old tool results must keep the prompt prefix stable, or every call misses the cache."""

from __future__ import annotations

from copy import deepcopy

from langchain.agents.middleware import ClearToolUsesEdit
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

from app.agent import middleware

# ~5k tokens a result: a db_query grid near its 6,000-char cap is ~1.5k, so this is a heavy turn.
RESULT = "row " * 5_000


def _edit() -> ClearToolUsesEdit:
    return middleware.clear_old_tool_results().edits[0]


def _conversation(calls: int, *, compare_fit_at: int | None = None) -> list:
    messages = [HumanMessage("What does Better Life Foundation do, and which funders fit it?")]
    for i in range(calls):
        name = "compare_fit" if i == compare_fit_at else "db_query"
        messages.append(AIMessage(content="", tool_calls=[{"name": name, "args": {"i": i}, "id": f"c{i}"}]))
        messages.append(ToolMessage(f"{name} {i} {RESULT}", tool_call_id=f"c{i}", name=name))
    return messages


def _sent(edit: ClearToolUsesEdit, messages: list) -> list:
    """What the model is sent: the edit runs on a copy, on every call, as ContextEditingMiddleware does."""
    edited = deepcopy(messages)
    edit.apply(edited, count_tokens=count_tokens_approximately)
    return [(type(m).__name__, m.content) for m in edited]


def _cache_breaks(edit: ClearToolUsesEdit, calls: int) -> int:
    """Calls whose prompt rewrites part of the previous call's prompt, so its cache entry cannot be read."""
    breaks, previous = 0, None
    for n in range(1, calls + 1):
        sent = _sent(edit, _conversation(n))
        if previous is not None and sent[: len(previous)] != previous:
            breaks += 1
        previous = sent
    return breaks


def test_the_cleared_set_changes_at_most_once_as_the_turn_grows():
    assert _cache_breaks(_edit(), 30) <= 1


def test_the_old_setting_broke_the_cache_on_every_call_past_the_trigger():
    old = ClearToolUsesEdit(trigger=40_000, keep=5)
    assert _cache_breaks(old, 30) > 10


def test_below_the_trigger_nothing_is_cleared():
    sent = _sent(_edit(), _conversation(5))
    assert not any(content == "[cleared]" for _, content in sent)


def test_past_the_trigger_old_results_are_cleared_but_compare_fit_never_is():
    sent = _sent(_edit(), _conversation(20, compare_fit_at=0))
    contents = [content for kind, content in sent if kind == "ToolMessage"]
    assert contents[0].startswith("compare_fit 0")
    assert "[cleared]" in contents
    # The latest results, which a follow-up refers back to, stay.
    assert all(c != "[cleared]" for c in contents[-middleware.TOOL_RESULTS_KEPT:])

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


def _sent_tokens(calls: int) -> int:
    edited = deepcopy(_conversation(calls))
    _edit().apply(edited, count_tokens=count_tokens_approximately)
    return count_tokens_approximately(edited)


def test_the_cleared_set_moves_once_per_step_as_the_turn_grows():
    # 30 results of ~5k is ~150k tokens: ~90k past the trigger, so at most five 20k steps.
    over = count_tokens_approximately(_conversation(30)) - middleware.TOOL_RESULT_CLEAR_TRIGGER_TOKENS
    assert _cache_breaks(_edit(), 30) <= -(-over // middleware.TOOL_RESULTS_CLEAR_STEP)


def test_what_is_sent_stays_under_the_trigger_however_long_the_turn():
    # A fixed clear_at_least cleared the same four results forever: 60 calls sent ~280k.
    for calls in (13, 17, 30, 60):
        assert _sent_tokens(calls) <= middleware.TOOL_RESULT_CLEAR_TRIGGER_TOKENS


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


class TestEveryFailedSqlAttemptCounts:
    def _failed(self, name: str, text: str, i: int) -> list:
        return [AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": f"f{i}"}]),
                ToolMessage(text, tool_call_id=f"f{i}", name=name)]

    def test_a_wrong_column_in_db_profile_column_counts_like_one_in_db_query(self):
        messages = [HumanMessage("which trusts work in Assam?"),
                    *self._failed("db_query", "db_query rejected: unknown column", 1),
                    *self._failed("db_profile_column", "db_profile_column rejected: orgs has no readable column", 2),
                    *self._failed("db_profile_column", "db_profile_column failed: timeout", 3)]
        assert middleware.count_failed_sql_attempts(messages) == 3

    async def test_its_rejections_carry_its_own_prefix(self):
        from app.agent.tools.sql_tools import db_profile_column

        reply = await db_profile_column.ainvoke({"table": "orgs", "column": "no_such_column"})
        assert reply.startswith("db_profile_column rejected:")

    def test_a_profile_that_worked_never_counts(self):
        messages = [HumanMessage("q"), *self._failed("db_profile_column", "orgs.legal_form — 3 most common", 1)]
        assert middleware.count_failed_sql_attempts(messages) == 0

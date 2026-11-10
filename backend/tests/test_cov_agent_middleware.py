"""The Ask and Import middleware hooks, called directly with hand-built state and requests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import middleware as mw
from app.agent.audit import CAVEAT_PREFIX, Audit
from app.agent.tools.sql.errors import FAILED_PREFIX, PROFILE_REJECTED_PREFIX


def _ai(*calls):
    return AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": i} for n, a, i in calls])


def _req(name, args=None, call_id="c1", state=None):
    return ToolCallRequest(tool_call={"name": name, "args": args or {}, "id": call_id, "type": "tool_call"},
                           tool=None, state=state if state is not None else {"messages": []}, runtime=None)


def _ok(request):
    return ToolMessage("ran", tool_call_id=request.tool_call["id"], name=request.tool_call["name"])


async def _aok(request):
    return _ok(request)


# --- sql retry limiter -------------------------------------------------------

def _failures(n):
    return [ToolMessage(f"{FAILED_PREFIX} x", tool_call_id=str(i), name="db_query") for i in range(n)]


def test_failures_are_counted_since_the_last_question_only():
    msgs = [*_failures(3), HumanMessage("again"), *_failures(2),
            ToolMessage(f"{PROFILE_REJECTED_PREFIX} y", tool_call_id="p", name="db_profile_column"),
            ToolMessage("fine", tool_call_id="q", name="db_query")]
    assert mw.count_failed_sql_attempts(msgs) == 3


def test_retry_limiter_lets_the_model_go_on_under_the_limit():
    assert mw.sql_retry_limiter.before_model({"messages": _failures(mw.MAX_SQL_ATTEMPTS - 1)}, None) is None


def test_retry_limiter_ends_the_turn_at_the_limit():
    out = mw.sql_retry_limiter.before_model({"messages": _failures(mw.MAX_SQL_ATTEMPTS)}, None)
    assert out["jump_to"] == "end" and "rephrase the question" in out["messages"][0].content


# --- model call cap ----------------------------------------------------------

def test_this_turn_without_a_human_message_is_everything():
    msgs = [AIMessage("a"), AIMessage("b")]
    assert mw._this_turn(msgs) == msgs


def test_model_call_cap_counts_this_turns_calls():
    cap = mw.model_call_cap(2)
    turn = [AIMessage("old"), AIMessage("old"), HumanMessage("q"), AIMessage("one")]
    assert cap.before_model({"messages": turn}, None) is None
    out = cap.before_model({"messages": [*turn, AIMessage("two")]}, None)
    assert out["jump_to"] == "end" and "narrower" in out["messages"][0].content


# --- compare_fit budget ------------------------------------------------------

def test_fit_key_sorts_funder_ids():
    assert mw._fit_key({"org_id": 1, "funder_ids": [3, 2]}) == (1, (2, 3))
    assert mw._fit_key({"org_id": 1}) == (1, None)


def test_a_repeat_compare_fit_is_refused():
    msgs = [HumanMessage("q"), _ai(("compare_fit", {"org_id": 1}, "a")), _ai(("db_query", {}, "x")),
            _ai(("compare_fit", {"org_id": 1}, "b"))]
    assert "refused a repeat" in mw.compare_fit_refusal(msgs, {"id": "b"})
    assert mw.compare_fit_refusal(msgs, {"id": "a"}) is None


def test_compare_fit_past_the_budget_is_refused():
    calls = [_ai(("compare_fit", {"org_id": 1, "funder_ids": [i]}, f"f{i}")) for i in range(4)]
    msgs = [HumanMessage("q"), *calls]
    assert "is the most for one question" in mw.compare_fit_refusal(msgs, {"id": "f3"})
    assert mw.compare_fit_refusal(msgs, {"id": "unknown"}) is None


def test_budget_middleware_refuses_or_runs():
    budget = mw.CompareFitBudget()
    state = {"messages": [HumanMessage("q"), _ai(("compare_fit", {"org_id": 1}, "a")),
                          _ai(("compare_fit", {"org_id": 1}, "b"))]}
    refused = budget.wrap_tool_call(_req("compare_fit", {"org_id": 1}, "b", state), _ok)
    assert refused.status == "error" and refused.name == "compare_fit"
    assert budget.wrap_tool_call(_req("db_query"), _ok).content == "ran"
    assert budget.wrap_tool_call(_req("compare_fit", {"org_id": 1}, "a", state), _ok).content == "ran"


async def test_budget_middleware_async_reads_object_state():
    budget = mw.CompareFitBudget()
    state = SimpleNamespace(messages=[HumanMessage("q"), _ai(("compare_fit", {"org_id": 1}, "a")),
                                      _ai(("compare_fit", {"org_id": 1}, "b"))])
    assert (await budget.awrap_tool_call(_req("compare_fit", {"org_id": 1}, "b", state), _aok)).status == "error"
    assert (await budget.awrap_tool_call(_req("db_query"), _aok)).content == "ran"


# --- tool errors and clearing ------------------------------------------------

def test_a_raised_tool_reports_only_the_exception_type():
    out = mw._tool_failed(RuntimeError("password=hunter2"), _req("db_query"))
    assert out.startswith("db_query failed: RuntimeError.") and "hunter2" not in out
    assert mw._tool_failed(ValueError(), SimpleNamespace(tool_call={})).startswith("tool failed")


def test_stepped_clearing_does_nothing_under_the_trigger():
    edit = mw.clear_old_tool_results().edits[0]
    msgs = [HumanMessage("hi")]
    edit.apply(msgs, count_tokens=lambda m: 10)
    assert msgs == [HumanMessage("hi")]


def test_tool_errors_builds_the_middleware():
    assert mw.tool_errors() is not None


# --- answer audit ------------------------------------------------------------

@pytest.fixture
def scores(monkeypatch):
    seen = []
    monkeypatch.setattr(mw, "score_answer", lambda name, value, comment=None: seen.append((name, value, comment)))
    return seen


def _audit_with(monkeypatch, verdict):
    monkeypatch.setattr(mw, "audit_turn", lambda messages, spec: verdict)
    return mw.answer_audit("haiku").after_agent({"messages": []}, None)


def test_no_verdict_scores_nothing(monkeypatch, scores):
    assert _audit_with(monkeypatch, None) is None and scores == []


def test_an_ok_verdict_scores_one_and_adds_nothing(monkeypatch, scores):
    assert _audit_with(monkeypatch, Audit("ok")) is None
    assert scores == [("answer_audit", 1.0, None)]


def test_a_warning_appends_a_caveat(monkeypatch, scores):
    out = _audit_with(monkeypatch, Audit("warn", "counts orgs twice"))
    assert out["messages"][0].content == f"{CAVEAT_PREFIX} counts orgs twice"
    assert scores == [("answer_audit", 0.0, "counts orgs twice")]


def test_a_warning_without_a_caveat_adds_nothing(monkeypatch, scores):
    assert _audit_with(monkeypatch, Audit("warn", None)) is None and scores[0][1] == 0.0


# --- staff-last lock ---------------------------------------------------------

def test_staff_rows_requested_by_call_or_result():
    assert not mw.staff_rows_requested([HumanMessage("q"), _ai(("read_page", {}, "a"))])
    assert mw.staff_rows_requested([_ai((mw.STAFF_TOOL, {}, "a"))])
    assert mw.staff_rows_requested([ToolMessage("rows", tool_call_id="a", name=mw.STAFF_TOOL)])


def test_staff_lock_closes_outbound_tools_after_a_staff_read():
    lock = mw.staff_last_lock()
    read = {"messages": [_ai((mw.STAFF_TOOL, {}, "s"))]}
    refused = lock.wrap_tool_call(_req("read_page", state=read), _ok)
    assert refused.content == mw.STAFF_LOCK_REPLY and refused.status == "error"
    assert lock.wrap_tool_call(_req("save_research", state=read), _ok).content == "ran"
    assert lock.wrap_tool_call(_req("read_page"), _ok).content == "ran"


async def test_staff_lock_fails_closed_on_unreadable_state():
    lock = mw.StaffLastLock()
    refused = await lock.awrap_tool_call(_req("read_page", state=SimpleNamespace()), _aok)
    assert refused.content == mw.STAFF_LOCK_REPLY
    clean = SimpleNamespace(messages=[HumanMessage("q")])
    assert (await lock.awrap_tool_call(_req("read_page", state=clean), _aok)).content == "ran"


# --- save questions ----------------------------------------------------------

def test_describe_names_the_slug_and_questions():
    sq = mw.save_questions()
    assert sq._describe({"id": "x", "args": {}}) == "Approve writing every researched organisation to the catalog"
    sq._previews["x"] = {"questions": [1, 2]}
    assert sq._describe({"id": "x", "args": {"slug": "kabil"}}) == "Approve writing kabil to the catalog (2 question(s))"


async def test_after_model_previews_each_save_and_forgets_them(monkeypatch):
    from app.ingest.tools import catalog_tools

    async def preview(slug):
        return {"questions": ["q1"], "planned": ["orgs"], "coverage": "8/10"}

    monkeypatch.setattr(catalog_tools, "write_preview", preview)
    sq = mw.SaveQuestions()
    seen = {}

    def after_model(state, runtime):
        last = state["messages"][-1]
        for call in last.tool_calls:
            config = sq.interrupt_on[mw.SAVE_TOOL]
            action, _ = sq._create_action_and_config(call, config, state, runtime)
            seen[call["id"]] = action
        return "paused"

    monkeypatch.setattr(sq, "after_model", after_model)
    state = {"messages": [HumanMessage("go"), _ai((mw.SAVE_TOOL, {"slug": "kabil"}, "s1"),
                                                  (mw.SAVE_TOOL, {"slug": ""}, "s2"),
                                                  ("read_page", {}, "r"))]}
    assert await sq.aafter_model(state, None) == "paused"
    assert seen["s1"]["questions"] == ["q1"] and seen["s1"]["coverage"] == "8/10"
    assert "(1 question(s))" in seen["s1"]["description"]
    assert seen["s2"]["questions"] == [] and seen["s2"]["planned"] == []
    assert sq._previews == {}


async def test_after_model_with_no_ai_message(monkeypatch):
    sq = mw.SaveQuestions()
    monkeypatch.setattr(sq, "after_model", lambda state, runtime: None)
    assert await sq.aafter_model({"messages": [HumanMessage("x")]}, None) is None


def test_sync_save_drops_model_written_decisions():
    sq = mw.SaveQuestions()
    out = sq.wrap_tool_call(_req(mw.SAVE_TOOL, {"slug": "k", "decisions": {"a": 1}}), lambda r: r.tool_call)
    assert out["args"] == {"slug": "k", "decisions": {}}
    assert sq.wrap_tool_call(_req("other"), _ok).content == "ran"


async def test_async_save_takes_decisions_only_from_a_persons_edit():
    sq = mw.SaveQuestions()

    async def echo(r):
        return r.tool_call

    model_wrote = await sq.awrap_tool_call(_req(mw.SAVE_TOOL, {"slug": "k", "decisions": {"a": 1}}), echo)
    assert model_wrote["args"]["decisions"] == {}

    edited = {"messages": [], "hitl_edited_tool_calls": {
        "c1": {"name": mw.SAVE_TOOL, "args": {"decisions": {"q1": "yes"}}}}}
    person = await sq.awrap_tool_call(_req(mw.SAVE_TOOL, {"slug": "k"}, state=edited), echo)
    assert person["args"] == {"slug": "k", "decisions": {"q1": "yes"}}

    bad = {"messages": [], "hitl_edited_tool_calls": {"c1": {"name": mw.SAVE_TOOL, "args": {"decisions": "x"}}}}
    assert (await sq.awrap_tool_call(_req(mw.SAVE_TOOL, {}, state=bad), echo))["args"]["decisions"] == {}
    assert (await sq.awrap_tool_call(_req("other"), _aok)).content == "ran"

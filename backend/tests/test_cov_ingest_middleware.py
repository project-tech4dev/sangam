"""Import's middleware hooks, each driven directly with a stand-in request and handler."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from deepagents.middleware.rubric import GraderResponse, RubricMiddleware
from langchain.agents.middleware import ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from app.ingest import middleware as mw
from app.ingest import run_sources
from app.ingest.run_sources import Sources
from tests.cov_ingest_fakes import running_as
from tests.test_import_roles import MEMBER, STAFF


class Request(SimpleNamespace):
    """Enough of ModelRequest/ToolCallRequest: fields, and override returning a changed copy."""

    def override(self, **changes):
        return Request(**{**self.__dict__, **changes})


def tool_request(name="read_page", args=None, call_id="c1", messages=()):
    return Request(tool_call={"name": name, "args": args or {}, "id": call_id}, state={"messages": list(messages)})


def reads(n: int) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": "read_page", "args": {}, "id": f"r{i}"} for i in range(n)])


class TestReadingLimit:
    def test_the_call_past_the_limit_is_refused_sync(self):
        limit = mw.ReadingLimit(2)
        msgs = [reads(3)]
        assert limit.wrap_tool_call(tool_request(call_id="r1", messages=msgs), lambda r: "read") == "read"
        out = limit.wrap_tool_call(tool_request(call_id="r2", messages=msgs), lambda r: "read")
        assert isinstance(out, ToolMessage) and mw.READING_LIMIT in out.content

    def test_other_tools_and_unknown_calls_pass(self):
        limit = mw.ReadingLimit(0)
        assert limit.wrap_tool_call(tool_request("save_research"), lambda r: "ok") == "ok"
        assert limit.wrap_tool_call(tool_request(call_id="zz", messages=[reads(1)]), lambda r: "ok") == "ok"

    def test_messages_from_an_object_state(self):
        assert mw._messages(SimpleNamespace(messages=[1])) == [1]
        assert mw._messages(None) == []


class TestSaveFailed:
    def test_an_error_status_or_text(self):
        bad = ToolMessage("Error invoking tool 'save_research'", tool_call_id="s", name="save_research")
        assert mw.save_failed([bad])
        assert mw.save_failed([ToolMessage("x", tool_call_id="s", name="save_research", status="error")])
        assert not mw.save_failed([ToolMessage("Saved", tool_call_id="s", name="save_research")])


URL = "https://example.org/a"


def research(**over) -> dict:
    return {"entity_name": "Acme Foundation", "entity_kind": "funder", "status": "not_found",
            "summary": "Nothing public about this one in any source read.", **over}


class TestRefusalText:
    def test_a_valid_payload_has_none(self):
        assert mw.refusal_text("save_research", research()) is None

    def test_an_unknown_finding_key_names_the_allowed_ones(self):
        finding = {"concept": "rfp", "title": "Call 2026", "source_url": URL, "confidence": "high",
                   "evidence": "The call for 2026 opens in May for NGOs.", "colour": "red"}
        out = mw.refusal_text("save_research", research(status="partial", stopped_reason="x", findings=[finding]))
        assert "finding 0 (rfp 'Call 2026'): `colour` is not a field of rfp. Allowed:" in out

    def test_top_level_extras(self):
        assert "`replace` is an argument beside `findings`" in mw.refusal_text(
            "save_research", research(replace=True))
        assert "top level: `colour` is not a field. Allowed:" in mw.refusal_text(
            "save_research", research(colour="red"))

    def test_a_non_dict_finding_and_a_missing_field(self):
        out = mw.refusal_text("save_research", research(findings=["x"], summary=None))
        assert "finding 0 (?)" in out and "top level summary" in out

    def test_long_lists_are_cut(self, monkeypatch):
        monkeypatch.setattr(mw, "REFUSAL_LINES", 1)
        out = mw.refusal_text("save_research", {"entity_kind": "x"})
        assert "- and" in out and "more of the same kinds" in out

    def test_a_string_that_is_not_json(self):
        assert "not valid JSON" in mw.refusal_text("save_research", "{oops")

    def test_vault_saves_use_their_own_schema(self):
        assert "Fix these" in mw.refusal_text("save_vault_findings", {"entity_name": "A"})


class TestSaveRefusal:
    def error(self):
        return ToolMessage("Error invoking tool 'save_research': long echo", tool_call_id="s",
                           name="save_research", status="error")

    def test_sync_rewrites_a_refused_save(self):
        req = tool_request("save_research", {"findings": {"entity_kind": "x"}})
        out = mw.SaveRefusal().wrap_tool_call(req, lambda r: self.error())
        assert out.content.startswith("Error invoking tool 'save_research': refused, nothing saved.")

    def test_an_unparseable_string_is_left_to_the_tool(self):
        req = tool_request("save_research", {"findings": "{nope"})
        seen = []
        mw.SaveRefusal().wrap_tool_call(req, lambda r: seen.append(r) or "ok")
        assert seen[0].tool_call["args"]["findings"] == "{nope"

    def test_a_rewrite_that_fails_keeps_the_original(self, monkeypatch):
        monkeypatch.setattr(mw, "refusal_text", lambda name, payload: 1 / 0)
        req = tool_request("save_research", {"findings": {}})
        assert mw.SaveRefusal().wrap_tool_call(req, lambda r: self.error()).content.endswith("long echo")

    def test_other_tools_pass_untouched(self):
        assert mw.SaveRefusal().wrap_tool_call(tool_request("read_page"), lambda r: "page") == "page"


class TestEscalation:
    def test_after_a_failed_save_the_strong_model_runs(self):
        bad = ToolMessage("x", tool_call_id="s", name="save_research", status="error")
        esc = mw.EscalateAfterFailedSave("strong")
        assert esc.wrap_model_call(Request(messages=[bad], model="weak"), lambda r: r.model) == "strong"
        assert esc.wrap_model_call(Request(messages=[], model="weak"), lambda r: r.model) == "weak"

    async def test_async(self):
        bad = ToolMessage("x", tool_call_id="s", name="save_research", status="error")

        async def handler(r):
            return r.model
        assert await mw.EscalateAfterFailedSave("strong").awrap_model_call(
            Request(messages=[bad], model="weak"), handler) == "strong"


class TestDropFiles:
    async def test_every_file_is_deleted_on_exit(self):
        drop = mw.DropFilesOnExit()
        assert drop.after_agent({"files": {"/a": 1, "/b": 2}}, None) == {"files": {"/a": None, "/b": None}}
        assert await drop.aafter_agent(SimpleNamespace(files={}), None) is None


class TestCallerNote:
    def test_the_note_follows_the_system_message(self):
        req = Request(system_message=SystemMessage("You are Scout."))
        with running_as(STAFF):
            out = mw.CallerNote().wrap_model_call(req, lambda r: r.system_message)
        assert out.content_blocks[0]["text"] == "You are Scout." and "Sangam team" in out.content_blocks[1]["text"]

    async def test_async_without_a_system_message(self):
        async def handler(r):
            return r.system_message
        with running_as(MEMBER):
            out = await mw.CallerNote().awrap_model_call(Request(system_message=None), handler)
        assert out.content_blocks[0]["text"].startswith("You are working for someone outside")


def ticked_state(value, description=mw.TICKED_SOURCES, as_objects=False):
    item = {"description": description, "value": value}
    item = SimpleNamespace(**item) if as_objects else item
    return {"ag-ui": {"context": [item]}, "messages": []}


class TestTickedSources:
    def test_a_json_string_is_read_and_cleaned(self):
        value = json.dumps({"web": True, "vault_org": "7", "vault_docs": [1, "x"], "staff_paths": ["a", 3]})
        assert mw.ticked_sources(ticked_state(value)) == {
            "web": True, "library": False, "vault_org": None, "vault_docs": [1], "staff_paths": ["a"]}

    def test_context_objects_are_read(self):
        state = ticked_state({"library": True, "vault_org": 7}, as_objects=True)
        assert mw.ticked_sources(state)["vault_org"] == 7

    @pytest.mark.parametrize("value", ["{bad", json.dumps([1]), {"web": False}, None])
    def test_nothing_usable_is_nothing_ticked(self, value):
        assert mw.ticked_sources(ticked_state(value)) is None

    def test_other_context_is_ignored(self):
        assert mw.ticked_sources(ticked_state({"web": True}, description="other")) is None
        assert mw.ticked_sources(None) is None

    def test_the_card_shows_only_when_nothing_was_ticked(self):
        assert mw.ask_for_sources(Request(state={}))
        assert not mw.ask_for_sources(Request(state=ticked_state({"web": True})))
        assert mw.ticked_note({}) is None
        assert "exactly these" in mw.ticked_note(ticked_state({"web": True}))

    def test_the_model_call_gets_the_ticks_whatever_it_passed(self):
        req = Request(state=ticked_state({"library": True}), system_message=SystemMessage("s"))
        call = {"name": run_sources.CHOOSE, "args": {"web": True}, "id": "c", "type": "tool_call"}
        other = {"name": "task", "args": {"x": 1}, "id": "t", "type": "tool_call"}

        def handler(r):
            assert "ticked these sources" in r.system_message.content_blocks[-1]["text"]
            return ModelResponse(result=[AIMessage("", tool_calls=[call, other])])
        out = mw.TickedSources().wrap_model_call(req, handler)
        [message] = out.result
        assert message.tool_calls[0]["args"]["library"] is True and message.tool_calls[1]["args"] == {"x": 1}

    async def test_async_with_nothing_ticked_leaves_the_call(self):
        req = Request(state={}, system_message=None)
        msg = AIMessage("", tool_calls=[{"name": run_sources.CHOOSE, "args": {"web": True}, "id": "c"}])

        async def handler(r):
            return msg
        out = await mw.TickedSources().awrap_model_call(req, handler)
        assert out.tool_calls[0]["args"] == {"web": True}

    def test_ai_messages_from_a_wrapped_response(self):
        inner = ModelResponse(result=[AIMessage("a"), HumanMessage("h")])
        assert [m.content for m in mw._ai_messages(SimpleNamespace(model_response=inner))] == ["a"]


def answered(artifact) -> list:
    return [AIMessage("", tool_calls=[{"name": "choose_sources", "args": {}, "id": "c"}]),
            ToolMessage("chosen", tool_call_id="c", name="choose_sources", artifact=artifact)]


class TestChosenAndRunSources:
    def test_sync_task_carries_the_answer(self):
        seen = {}

        def handler(r):
            seen["s"] = run_sources.CURRENT.get()
            return "done"
        req = tool_request("task", messages=answered({"web": True}))
        assert mw.ChosenSources().wrap_tool_call(req, handler) == "done"
        assert seen["s"] == Sources(web=True) and run_sources.CURRENT.get() is None

    def test_sync_task_before_the_answer_is_refused(self):
        out = mw.ChosenSources().wrap_tool_call(tool_request("task"), lambda r: pytest.fail("launched"))
        assert out.status == "error" and "choose_sources first" in out.content

    def test_unreadable_state_fails_closed(self, monkeypatch):
        monkeypatch.setattr(run_sources, "chosen", lambda messages: 1 / 0)
        out = mw.ChosenSources().wrap_tool_call(tool_request("task"), lambda r: pytest.fail("launched"))
        assert "choose_sources first" in out.content

    def test_other_tools_pass(self):
        assert mw.ChosenSources().wrap_tool_call(tool_request("read_page"), lambda r: "ok") == "ok"

    async def test_async_other_tools_pass(self):
        async def handler(r):
            return "ok"
        assert await mw.ChosenSources().awrap_tool_call(tool_request("read_page"), handler) == "ok"

    def test_run_sources_sync(self):
        out = mw.RunSources().wrap_tool_call(tool_request("read_page"), lambda r: "read")
        assert isinstance(out, ToolMessage) and out.status == "error"
        assert mw.RunSources().wrap_tool_call(tool_request("save_research"), lambda r: "saved") == "saved"


def grader_error(criteria) -> ValidationError:
    try:
        GraderResponse.model_validate({"result": "needs_revision", "explanation": "fine", "criteria": criteria})
    except ValidationError as exc:
        return exc
    raise AssertionError("validated")


class TestRubric:
    def test_all_passed_turns_a_contradiction_into_satisfied(self):
        exc = grader_error([{"name": "cited", "passed": True}])
        wrapped = RuntimeError("structured output failed")
        wrapped.__cause__ = exc
        verdict = mw.all_passed(wrapped)
        assert verdict.result == "satisfied" and verdict.criteria == [{"name": "cited", "passed": True}]

    def test_any_other_error_is_none(self):
        assert mw.all_passed(RuntimeError("x")) is None
        try:
            GraderResponse.model_validate({"result": "maybe"})
        except ValidationError as exc:
            assert mw.all_passed(exc) is None

    def test_a_cycle_of_causes_ends(self):
        a, b = RuntimeError("a"), RuntimeError("b")
        a.__cause__, b.__cause__ = b, a
        assert mw.all_passed(a) is None

    def test_stopped_by_call_limit(self):
        assert mw.stopped_by_call_limit({"messages": [AIMessage(f"{mw.CALL_LIMIT_PREFIX} (3)"), HumanMessage("x")]})
        assert not mw.stopped_by_call_limit({"messages": [AIMessage("done")]})
        assert not mw.stopped_by_call_limit({"messages": []})

    @pytest.fixture
    def rubric(self, monkeypatch):
        seen = {}

        def before(self, state, runtime):
            seen["before"] = state
            return {"before": True}

        async def abefore(self, state, runtime):
            seen["abefore"] = state
            return {"abefore": True}

        def after(self, state, runtime):
            return {"graded": state["rubric"] == mw.RUBRIC}

        async def aafter(self, state, runtime):
            return {"agraded": True}

        def handle(self, runtime, state, run_id, iteration, exc):
            return {"super": str(exc)}
        for name, fn in [("before_agent", before), ("abefore_agent", abefore), ("after_agent", after),
                         ("aafter_agent", aafter), ("_handle_grader_exception", handle)]:
            monkeypatch.setattr(RubricMiddleware, name, fn)
        r = mw.research_rubric(FakeListChatModel(responses=["x"]))
        monkeypatch.setattr(r, "_finalize_evaluation",
                            lambda graded, state, runtime, run_id, iteration: {"final": graded.result})
        return r, seen

    async def test_the_rubric_is_supplied_never_stored(self, rubric):
        r, seen = rubric
        assert r.before_agent({"messages": []}, None) == {"before": True}
        assert await r.abefore_agent({"messages": []}, None) == {"abefore": True}
        assert seen["before"]["rubric"] == mw.RUBRIC and seen["abefore"]["rubric"] == mw.RUBRIC

    async def test_a_run_ended_by_the_call_limit_is_not_graded(self, rubric):
        r, _ = rubric
        stopped = {"messages": [AIMessage(f"{mw.CALL_LIMIT_PREFIX}.")]}
        assert r.after_agent(stopped, None) is None and await r.aafter_agent(stopped, None) is None
        assert r.after_agent({"messages": []}, None) == {"graded": True}
        assert await r.aafter_agent({"messages": []}, None) == {"agraded": True}

    def test_a_contradictory_verdict_is_finalised_as_satisfied(self, rubric):
        r, _ = rubric
        exc = grader_error([{"name": "cited", "passed": True}])
        assert r._handle_grader_exception(None, {}, "g", 1, exc) == {"final": "satisfied"}
        assert r._handle_grader_exception(None, {}, "g", 1, RuntimeError("down")) == {"super": "down"}

    def test_the_log_line(self, caplog):
        with caplog.at_level("INFO"):
            mw._log_evaluation({"result": "satisfied", "iteration": 1})
        assert "research rubric: satisfied" in caplog.text

    def test_a_string_save_is_digested(self):
        payload = json.dumps({"status": "partial", "findings": [{"concept": "program", "name": "Water"}],
                              "gaps": [{"concept": "rfp", "reason": "not_stated", "detail": "none"}]})
        save = {"name": mw.SAVE_TOOL, "args": {"findings": payload}, "id": "s"}
        [out] = mw.digest_saves([AIMessage("", tool_calls=[save])])
        args = out.tool_calls[0]["args"]
        assert args["finding_count"] == 1 and args["programs_untagged"] == ["Water"]
        assert args["gaps"][0]["concept"] == "rfp"


class TestBuilders:
    def test_fallback_picks_the_first_different_model(self, monkeypatch):
        monkeypatch.setattr(mw, "resolve_model", lambda name: FakeListChatModel(responses=[name]))
        assert mw.fallback("a", "a", "", "b", "c")[0].models[0].responses == ["b"]
        assert mw.fallback("a", "a", "") == []

    def test_call_limit_plan_and_summarizer(self):
        assert mw.call_limit(5).run_limit == 5
        assert mw.run_plan().system_prompt == mw.PLAN_PROMPT
        assert mw.append_to_system_message(None, "x").content_blocks == [{"type": "text", "text": "x"}]

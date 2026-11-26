"""Import's middleware hooks, each driven directly with a stand-in request and handler."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command

from app.agentkit import middleware as kit
from app.ingest import middleware as mw
from app.ingest.reading import run_sources, snapshots
from app.ingest.reading.run_sources import Sources
from app.ingest.research import draft
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


URL = "https://example.org/a"
VAULT = "save_vault_findings"


def vault(**over) -> dict:
    return {"entity_name": "Acme Foundation", "entity_kind": "funder", "org_id": 7, "documents_read": [3], **over}


class TestRefusalText:
    def test_a_valid_payload_has_none(self):
        assert mw.refusal_text(VAULT, vault()) is None

    def test_an_unknown_finding_key_names_the_allowed_ones(self):
        finding = {"concept": "rfp", "title": "Call 2026", "source_url": URL, "confidence": "high",
                   "evidence": "The call for 2026 opens in May for NGOs.", "colour": "red"}
        out = mw.refusal_text(VAULT, vault(findings=[finding]))
        assert "finding 0 (rfp 'Call 2026'): `colour` is not a field of rfp. Allowed:" in out

    def test_top_level_extras(self):
        assert "top level: `colour` is not a field. Allowed:" in mw.refusal_text(VAULT, vault(colour="red"))

    def test_a_non_dict_finding_and_a_missing_field(self):
        out = mw.refusal_text(VAULT, vault(findings=["x"], org_id=None))
        assert "finding 0 (?)" in out and "top level org_id" in out

    def test_long_lists_are_cut(self, monkeypatch):
        monkeypatch.setattr(mw, "REFUSAL_LINES", 1)
        out = mw.refusal_text(VAULT, {"entity_kind": "x"})
        assert "- and" in out and "more of the same kinds" in out

    def test_a_string_that_is_not_json(self):
        assert "not valid JSON" in mw.refusal_text(VAULT, "{oops")


class TestSaveRefusal:
    def error(self):
        return ToolMessage(f"Error invoking tool '{VAULT}': long echo", tool_call_id="s", name=VAULT, status="error")

    def test_sync_rewrites_a_refused_save(self):
        req = tool_request(VAULT, {"findings": {"entity_kind": "x"}})
        out = mw.SaveRefusal().wrap_tool_call(req, lambda r: self.error())
        assert out.content.startswith(f"Error invoking tool '{VAULT}': refused, nothing saved.")

    def test_a_string_payload_is_parsed_first(self):
        seen = []
        mw.SaveRefusal().wrap_tool_call(tool_request(VAULT, {"findings": json.dumps(vault()) + "}"}),
                                        lambda r: seen.append(r) or "ok")
        assert seen[0].tool_call["args"]["findings"] == vault()

    def test_an_unparseable_string_is_left_to_the_tool(self):
        req = tool_request(VAULT, {"findings": "{nope"})
        seen = []
        mw.SaveRefusal().wrap_tool_call(req, lambda r: seen.append(r) or "ok")
        assert seen[0].tool_call["args"]["findings"] == "{nope"

    def test_a_rewrite_that_fails_keeps_the_original(self, monkeypatch):
        monkeypatch.setattr(mw, "refusal_text", lambda name, payload: 1 / 0)
        req = tool_request(VAULT, {"findings": {}})
        assert mw.SaveRefusal().wrap_tool_call(req, lambda r: self.error()).content.endswith("long echo")

    def test_other_tools_pass_untouched(self):
        assert mw.SaveRefusal().wrap_tool_call(tool_request("read_page"), lambda r: "page") == "page"
        assert mw.SaveRefusal().wrap_tool_call(tool_request("save_research"), lambda r: "saved") == "saved"


class TestEscalation:
    def test_only_two_content_refusals_move_the_run(self):
        esc = mw.EscalateAfterFailedSave("strong")
        assert esc.wrap_model_call(Request(messages=[], model="weak"), lambda r: r.model) == "weak"
        with draft.drafting() as current:
            current.refusals = 1
            assert esc.wrap_model_call(Request(messages=[], model="weak"), lambda r: r.model) == "weak"
            current.refusals = mw.ESCALATE_AFTER
            assert esc.wrap_model_call(Request(messages=[], model="weak"), lambda r: r.model) == "strong"

    def test_a_format_error_never_escalates(self):
        # c2b6973d: one string payload moved the run to Opus for $1.72.
        bad = ToolMessage("Error invoking tool 'save_research'", tool_call_id="s", name="save_research", status="error")
        with draft.drafting():
            esc = mw.EscalateAfterFailedSave("strong")
            assert esc.wrap_model_call(Request(messages=[bad], model="weak"), lambda r: r.model) == "weak"

    async def test_async(self):
        async def handler(r):
            return r.model
        with draft.drafting() as current:
            current.refusals = 2
            assert await mw.EscalateAfterFailedSave("strong").awrap_model_call(
                Request(messages=[], model="weak"), handler) == "strong"


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

    def test_check_changes_waits_for_the_answer_and_needs_the_web_tick(self):
        never = lambda r: pytest.fail("checked")
        out = mw.ChosenSources().wrap_tool_call(tool_request("check_changes"), never)
        assert out.status == "error" and "choose_sources first" in out.content
        vault_only = tool_request("check_changes", messages=answered({"web": False, "vault_org": 3}))
        assert "public websites" in mw.ChosenSources().wrap_tool_call(vault_only, never).content
        web = tool_request("check_changes", messages=answered({"web": True}))
        assert mw.ChosenSources().wrap_tool_call(web, lambda r: "checked") == "checked"
        assert run_sources.CURRENT.get() is None

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


def task_result(content: str) -> Command:
    return Command(update={"messages": [ToolMessage(content, tool_call_id="t")], "files": {}})


SAVED = {"slug": "acme", "entity_kind": "funder", "status": "partial", "fact_count": 41, "source_count": 6,
         "concepts_found": ["csr_spend", "rfp"], "not_found": ["metric"]}


class TestTheSummaryCountsComeFromTheSave:
    def summary(self, **over) -> str:
        return json.dumps({"slug": "acme", "entity_name": "Acme", "status": "partial", "entity_kind": "unknown",
                           "fact_count": 3, "concepts_found": [], "saved": False, **over})

    def test_the_counts_the_model_wrote_are_replaced(self):
        current = draft.Draft(saved=SAVED)
        out = mw.with_saved_counts(task_result(self.summary()), current)
        summary = json.loads(out.update["messages"][-1].content)
        assert (summary["fact_count"], summary["entity_kind"], summary["saved"]) == (41, "funder", True)
        assert summary["concepts_found"] == ["csr_spend", "rfp"] and summary["entity_name"] == "Acme"
        assert summary["status"] == "partial" and out.update["files"] == {}

    @pytest.mark.parametrize("result", [
        "plain",
        task_result("not json"),
        task_result(json.dumps({"entities": []})),
        Command(update={"messages": []}),
    ])
    def test_anything_else_passes_untouched(self, result):
        assert mw.with_saved_counts(result, draft.Draft(saved=SAVED)) is result

    def test_nothing_saved_changes_nothing(self):
        result = task_result(self.summary())
        assert mw.with_saved_counts(result, draft.Draft()) is result
        assert mw.with_saved_counts(result, None) is result

    def test_recorded_but_never_saved_says_so(self):
        # The draft dies with the run, so "saved: true, 40 facts" from the model must not reach the supervisor.
        current = draft.Draft(findings=[{"concept": "rfp"}] * 2)
        out = mw.with_saved_counts(task_result(self.summary(saved=True, fact_count=40)), current)
        summary = json.loads(out.update["messages"][-1].content)
        assert (summary["saved"], summary["fact_count"]) == (False, 0) and "2 findings" in summary["not_saved"]

    def test_each_task_gets_its_own_draft_and_snapshot_list(self):
        seen = {}

        def handler(r):
            seen["draft"], seen["ids"] = draft.CURRENT.get(), snapshots.COLLECTED.get()
            seen["draft"].saved = SAVED
            return task_result(self.summary())
        out = mw.ChosenSources().wrap_tool_call(tool_request("task", messages=answered({"web": True})), handler)
        assert isinstance(seen["draft"], draft.Draft) and seen["ids"] == []
        assert json.loads(out.update["messages"][-1].content)["fact_count"] == 41
        assert draft.CURRENT.get() is None and snapshots.COLLECTED.get() is None

    async def test_async_task_too(self):
        async def handler(r):
            draft.CURRENT.get().saved = SAVED
            return task_result(self.summary())
        out = await mw.ChosenSources().awrap_tool_call(tool_request("task", messages=answered({"web": True})), handler)
        assert json.loads(out.update["messages"][-1].content)["saved"] is True


class TestBuilders:
    def test_fallback_picks_the_first_different_model(self, monkeypatch):
        monkeypatch.setattr(kit, "resolve_model", lambda name: FakeListChatModel(responses=[name]))
        assert kit.fallback("a", "a", "", "b", "c")[0].models[0].responses == ["b"]
        assert kit.fallback("a", "a", "") == []

    def test_call_limit_plan_and_summarizer(self):
        assert mw.call_limit(5).run_limit == 5
        assert mw.run_plan().system_prompt == mw.PLAN_PROMPT
        assert mw.append_to_system_message(None, "x").content_blocks == [{"type": "text", "text": "x"}]

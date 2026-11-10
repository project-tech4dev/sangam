"""A question asked mid-run is answered from the checkpoint and the Working board, never the running graph."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.ingest import live_status
from app.schemas.ingest import AskLiveIn
from tests.cov_ingest_fakes import ScriptConn, ScriptPool

ME = UUID(int=2)


def messages() -> list:
    return [
        HumanMessage("first ask"),
        HumanMessage("Research Acme and Pratham"),
        AIMessage("", tool_calls=[{"name": "task", "id": "t1", "args": {"description": "Research Acme " * 30}},
                                  {"name": "read_page", "id": "r1", "args": {}}]),
        ToolMessage("Chosen: web yes", tool_call_id="c", name="choose_sources"),
        ToolMessage(json.dumps({"entity_name": "Acme", "status": "complete", "fact_count": 12, "x": 1}),
                    tool_call_id="t1", name="task"),
        ToolMessage("not json at all", tool_call_id="t2", name="task"),
        ToolMessage(json.dumps(["a list"]), tool_call_id="t3", name="task"),
    ]


class TestRunState:
    def test_reads_the_latest_ask_sources_launches_and_returns(self):
        state = live_status.run_state(messages())
        assert state["asked"] == ["Research Acme and Pratham"]
        assert state["sources"] == "Chosen: web yes"
        assert len(state["launched"]) == 1 and len(state["launched"][0]) == 200
        assert state["returned"] == [{"entity_name": "Acme", "status": "complete", "fact_count": 12,
                                      "not_found": None}]

    def test_an_empty_run(self):
        assert live_status.run_state([]) == {"asked": [], "sources": None, "launched": [], "returned": []}


class TestProgress:
    def test_counts_per_researcher(self):
        body = AskLiveIn(question="how far?", steps=[
            {"owner": "Acme", "tool": "search_public_sources"},
            {"owner": "Acme", "tool": "read_page"},
            {"owner": "Acme", "tool": "save_research", "running": False},
            {"owner": None, "tool": "fetch_document", "running": True},
        ])
        out = live_status.progress(body)
        assert out["Acme"] == {"searches": 1, "reads": 1, "saved": True, "working": False}
        assert out["Scout"] == {"searches": 0, "reads": 1, "saved": False, "working": True}


class TestSavedSince:
    async def test_no_since_reads_nothing(self):
        assert await live_status.saved_since(ScriptPool(), ME, None) == []

    async def test_reads_this_callers_saves(self):
        pool = ScriptPool(ScriptConn([("entity_research", [{"entity_name": "Acme"}])]))
        since = datetime(2026, 10, 1, tzinfo=UTC)
        assert await live_status.saved_since(pool, ME, since) == [{"entity_name": "Acme"}]
        assert pool.conn.calls[0][1] == (since, ME)


class _Model:
    def __init__(self, reply):
        self.reply, self.seen = reply, None

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        self.seen = messages
        return self.reply


class _Graph:
    async def aget_state(self, config):
        assert config == {"configurable": {"thread_id": "import-1"}}
        return SimpleNamespace(values={"messages": messages(), "todos": [{"content": "Acme"}]})


class TestAnswer:
    async def run(self, monkeypatch, reply):
        model = _Model(reply)
        monkeypatch.setattr(live_status, "resolve_model", lambda name: model)
        settings = SimpleNamespace(utility_model="haiku")
        body = AskLiveIn(question="Is Acme done?", steps=[{"owner": "Acme", "tool": "read_page"}])
        out = await live_status.answer(_Graph(), ScriptPool(), "import-1", ME, body, settings)
        return out, model

    async def test_the_state_reaches_the_model_and_its_answer_returns(self, monkeypatch):
        out, model = await self.run(monkeypatch, live_status._Answer(answer="Acme is saved.", kind="instruction"))
        assert out.answer == "Acme is saved." and out.kind == "instruction"
        human = model.seen[1].content
        assert "Question: Is Acme done?" in human and '"plan": [{"content": "Acme"}]' in human

    async def test_an_unknown_kind_is_status(self, monkeypatch):
        out, _ = await self.run(monkeypatch, live_status._Answer(answer="Working.", kind="chatter"))
        assert out.kind == "status"

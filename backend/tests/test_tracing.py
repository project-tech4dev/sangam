"""Tracing wiring: what reaches Langfuse, and what happens when it can't load."""

from __future__ import annotations

import sys
import types

import pytest
from ag_ui.core.types import RunAgentInput

from app.core.config import Settings
from app.core.security import DEV_USER_ID
from app.integrations.tracing import TRACE_NAME, SessionScopedAGUIAgent, trace_config

ENABLED = {"langfuse_public_key": "pk", "langfuse_secret_key": "sk"}


@pytest.fixture
def fake_langfuse(monkeypatch):
    """Stand in for the SDK so the success path is testable without it installed."""
    seen: dict = {}

    class CallbackHandler:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    mod = types.ModuleType("langfuse.langchain")
    mod.CallbackHandler = CallbackHandler
    parent = types.ModuleType("langfuse")
    parent.langchain = mod
    monkeypatch.setitem(sys.modules, "langfuse", parent)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", mod)
    return seen


def test_names_the_run_even_when_tracing_is_off():
    # Without a run name every trace is called "LangGraph"; the name is set
    # whether or not Langfuse is configured so the graph is identified either way.
    config = trace_config(Settings(langfuse_public_key="", langfuse_secret_key=""))
    assert config == {"run_name": TRACE_NAME}
    assert "callbacks" not in config


def test_attaches_handler_with_update_trace(fake_langfuse):
    config = trace_config(Settings(**ENABLED))
    assert config["run_name"] == TRACE_NAME
    assert len(config["callbacks"]) == 1
    # update_trace is what lifts name/input/output onto the trace itself.
    assert fake_langfuse["update_trace"] is True


def test_handler_is_bound_to_the_configured_client(fake_langfuse):
    """The mask lives on the client configure_langfuse() registered under our public key. A handler
    built without that key makes its own client from the"""
    trace_config(Settings(**ENABLED))
    assert fake_langfuse["public_key"] == "pk"


def test_tags_carry_the_model(fake_langfuse):
    config = trace_config(Settings(**ENABLED, model="anthropic:claude-sonnet-5"))
    assert config["metadata"]["langfuse_tags"] == ["sangam", "anthropic:claude-sonnet-5"]


def test_broken_sdk_degrades_instead_of_raising(monkeypatch):
    """A missing or broken langfuse must not stop the app from booting."""
    broken = types.ModuleType("langfuse.langchain")

    def explode(*_a, **_k):
        raise RuntimeError("no SDK here")

    broken.__getattr__ = explode
    monkeypatch.setitem(sys.modules, "langfuse.langchain", broken)

    config = trace_config(Settings(**ENABLED))
    assert config == {"run_name": TRACE_NAME}


async def test_run_is_tagged_with_its_conversation(monkeypatch):
    """Langfuse groups by langfuse_session_id and ignores thread_id, so the
    AG-UI thread has to be mapped onto it or each turn is an orphan trace."""
    captured: dict = {}

    async def fake_super(self, *, input, agent_state, config):
        captured.update(config)

    monkeypatch.setattr(
        "app.integrations.tracing.LangGraphAGUIAgent.prepare_stream", fake_super, raising=True
    )
    agent = SessionScopedAGUIAgent.__new__(SessionScopedAGUIAgent)
    await agent.prepare_stream(
        input=RunAgentInput(thread_id="thread-42", run_id="run-1", messages=[]),
        agent_state={},
        config={"metadata": {"langfuse_tags": ["sangam"]}},
    )

    assert captured["metadata"]["langfuse_session_id"] == "thread-42"
    assert captured["metadata"]["langfuse_user_id"] == str(DEV_USER_ID)
    assert captured["metadata"]["agui_run_id"] == "run-1"
    # existing metadata survives the merge
    assert captured["metadata"]["langfuse_tags"] == ["sangam"]


async def test_graph_and_request_metadata_both_survive():
    """The design splits trace attributes across two layers: static tags are bound to the graph,
    session/user are added per request. LangChain has to"""
    from langchain_core.callbacks import AsyncCallbackHandler
    from langchain_core.runnables import RunnableLambda

    seen: dict = {}

    class Spy(AsyncCallbackHandler):
        async def on_chain_start(self, serialized, inputs, **kwargs):
            seen.setdefault("metadata", kwargs.get("metadata") or {})
            seen.setdefault("name", kwargs.get("name"))

    bound = RunnableLambda(lambda x: x, name="LangGraph").with_config(
        {**trace_config(Settings(langfuse_public_key="", langfuse_secret_key="")),
         "callbacks": [Spy()],
         "metadata": {"langfuse_tags": ["sangam"]}}
    )
    await bound.ainvoke({}, config={"metadata": {"langfuse_session_id": "thread-42"}})

    assert seen["name"] == TRACE_NAME  # not "LangGraph"
    assert seen["metadata"]["langfuse_tags"] == ["sangam"]
    assert seen["metadata"]["langfuse_session_id"] == "thread-42"


class _FakeCursor:
    def __init__(self, rows): self._rows = rows
    async def fetchall(self): return self._rows


class _FakeConn:
    def __init__(self, rows): self._rows = rows; self.calls = []
    async def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _FakeCursor(self._rows)


async def test_traced_fetch_returns_rows_without_tracing():
    """No Langfuse in the process must not stop a query from running."""
    from app.integrations.tracing import traced_fetch

    conn = _FakeConn([{"id": 1}, {"id": 2}])
    rows = await traced_fetch(conn, "SELECT 1", {"q": "x"}, name="t.q")
    assert rows == [{"id": 1}, {"id": 2}]
    assert conn.calls == [("SELECT 1", {"q": "x"})]


async def test_traced_fetch_records_sql_and_row_count(monkeypatch):
    """The trace has to carry the statement — a tool's args and its formatted
    output do not tell you which query produced the rows."""
    import contextlib
    import types

    from app.integrations import tracing

    recorded: dict = {}

    class FakeSpan:
        def update(self, **kw): recorded.update(kw)

    class FakeClient:
        @contextlib.contextmanager
        def start_as_current_observation(self, *, name, as_type, input):
            recorded["name"] = name
            recorded["as_type"] = as_type
            recorded["input"] = input
            yield FakeSpan()

    mod = types.ModuleType("langfuse")
    mod.get_client = lambda: FakeClient()
    monkeypatch.setitem(sys.modules, "langfuse", mod)

    conn = _FakeConn([{"id": 1}])
    await tracing.traced_fetch(
        conn, "\n    SELECT o.id\n    FROM orgs o\n    ", {"q": "kabil"}, name="query-orgs"
    )

    assert recorded["name"] == "query-orgs"
    # retrieval-typed so Langfuse's retrieval evaluators can see these
    assert recorded["as_type"] == "retriever"
    # dedented, so the SQL reads as SQL rather than as indented Python
    assert recorded["input"]["sql"] == "SELECT o.id\nFROM orgs o"
    assert recorded["input"]["params"] == {"q": "kabil"}
    assert recorded["output"] == {"row_count": 1}


def test_recursion_limit_reaches_the_graph():
    """Settings.recursion_limit existed for months without being bound to the graph, so LangGraph
    silently used its default of 25. Nothing caught it while"""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent.build import build_agent

    settings = Settings(recursion_limit=137)
    graph = build_agent(settings, InMemorySaver())
    assert graph.config["recursion_limit"] == 137


def test_recursion_limit_leaves_room_for_a_real_sql_turn():
    """Twelve tool calls was the worst observed (a full funder profile), and each model-then-tool cycle
    costs several graph steps because every middleware hook"""
    assert Settings().recursion_limit >= 150


class TestMasking:
    """Tool outputs carry real warehouse rows — org records, contact names, grant amounts. A trace
    holding those is only acceptable on a Langfuse"""

    RESULT = (
        "3 row(s).\n"
        "adjusted: no LIMIT was given, so LIMIT 50 was applied.\n"
        "caveats: All 10 districts currently parent to Assam.\n"
        'executed: SELECT "o"."id", "o"."name" FROM "orgs" AS "o" LIMIT 51\n'
        "columns: name\n"
        "[org:9] KABIL\n"
        "[org:1] AJAGAR SOCIAL CIRCLE\n"
        "[org:8] THE ANT"
    )

    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_MASK_TOOL_RESULTS", raising=False)
        from app.integrations.tracing import mask_payload, masking_enabled

        assert masking_enabled() is False
        assert mask_payload(data=self.RESULT) == self.RESULT

    def test_rows_are_redacted_when_on(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "true")
        from app.integrations.tracing import mask_payload

        out = mask_payload(data=self.RESULT)
        for row in ("KABIL", "AJAGAR SOCIAL CIRCLE", "THE ANT"):
            assert row not in out, f"{row} reached the trace"
        assert "3 row(s) redacted" in out

    def test_what_you_debug_with_survives(self, monkeypatch):
        """Redacting the SQL too would make the trace useless — the query is
        the thing you read a trace to see."""
        monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "true")
        from app.integrations.tracing import mask_payload

        out = mask_payload(data=self.RESULT)
        assert "SELECT" in out and "orgs" in out
        assert "3 row(s)." in out
        assert "caveats:" in out

    def test_nested_payloads_are_masked(self, monkeypatch):
        """The handler sends dicts and lists, not just strings."""
        monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "true")
        from app.integrations.tracing import mask_payload

        out = mask_payload(data={"output": [self.RESULT], "sql": "SELECT 1"})
        assert "KABIL" not in str(out)
        assert out["sql"] == "SELECT 1"

    def test_long_payloads_are_clipped_regardless(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_MASK_TOOL_RESULTS", raising=False)
        from app.integrations.tracing import MAX_IO_CHARS, mask_payload

        assert len(mask_payload(data="x" * 50_000)) == MAX_IO_CHARS

    def test_a_broken_mask_does_not_drop_the_batch(self, monkeypatch):
        from app.integrations import tracing

        monkeypatch.setattr(
            tracing, "masking_enabled", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        assert tracing.mask_payload(data="payload") == "payload"


async def test_a_cancelled_turn_is_not_an_error(fake_langfuse):
    """A browser disconnect cancels the streaming task mid-turn. The SDK exempts LangGraph's
    GraphBubbleUp but not asyncio.CancelledError, so every"""
    import asyncio

    from app.integrations.tracing import _build_handler

    handler = _build_handler(Settings(**ENABLED))
    ended: dict = {}

    class FakeObservation:
        def update(self, **kw):
            ended.update(kw)
            return self

        def end(self):
            ended["ended"] = True

    handler._detach_observation = lambda run_id: FakeObservation()
    handler.on_chain_error(asyncio.CancelledError(), run_id="r1")

    assert ended.get("ended") is True
    assert "cancelled" in ended.get("status_message", "")
    assert ended.get("level") != "ERROR"


class TestRedactionIsShapeAware:
    """Redaction must recognise DATA, not guess at not-metadata. An earlier version stubbed every line
    that did not look like metadata, which destroyed"""

    def test_bare_sql_survives(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "true")
        from app.integrations.tracing import mask_payload

        sql = 'SELECT "o"."id" FROM "orgs" AS "o" LIMIT 51'
        assert mask_payload(data={"sql": sql, "params": None})["sql"] == sql

    def test_prose_survives(self, monkeypatch):
        """Model inputs and answers have no grid header and must pass through."""
        monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "true")
        from app.integrations.tracing import mask_payload

        prose = "Which organisations work in Assam?\nSeven, per org_locations."
        assert mask_payload(data=prose) == prose

    def test_profile_values_are_redacted(self, monkeypatch):
        """db_profile_column prints real stored values, which are data too."""
        monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "true")
        from app.integrations.tracing import mask_payload

        out = mask_payload(
            data="orgs.legal_form — 3 most common value(s), as stored:\n"
            "  Society  (7)\n  Trust  (1)"
        )
        assert "Society" not in out and "Trust" not in out
        assert "as stored:" in out
        assert "2 row(s) redacted" in out

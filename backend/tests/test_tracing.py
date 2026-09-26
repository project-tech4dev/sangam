"""Tracing wiring: what reaches Langfuse, and what happens when it can't load.

These are the first tests over agent construction, so they deliberately cover
the degradation path as well as the happy one — tracing that raises would take
the whole app down at boot.
"""

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
    assert fake_langfuse == {"update_trace": True}


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
    """The design splits trace attributes across two layers: static tags are
    bound to the graph, session/user are added per request. LangChain has to
    merge them or one set is silently dropped — this pins that behaviour."""
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

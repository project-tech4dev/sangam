"""Tracing helpers and the handler's overrides, with a fake Langfuse SDK in place of the real one."""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest
from ag_ui.core.types import RunAgentInput
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.config import Settings
from app.integrations import tracing

ENABLED = {"langfuse_public_key": "pk", "langfuse_secret_key": "sk"}


def _install(monkeypatch, **attrs):
    mod = types.ModuleType("langfuse")
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, "langfuse", mod)
    return mod


# --- masking -----------------------------------------------------------------

def test_masking_reads_the_env(monkeypatch):
    monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "yes")
    assert tracing.masking_enabled()
    monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "0")
    assert not tracing.masking_enabled()


@pytest.mark.parametrize("text", ["no header here", "columns: id, name", "columns: id\n   \n"])
def test_redact_leaves_text_without_rows(text):
    assert tracing._redact_rows(text) == text


def test_mask_clips_long_strings_and_walks_lists(monkeypatch):
    monkeypatch.delenv("LANGFUSE_MASK_TOOL_RESULTS", raising=False)
    out = tracing.mask_payload(data=["x" * (tracing.MAX_IO_CHARS + 5), 3, {"k": "v"}])
    assert len(out[0]) == tracing.MAX_IO_CHARS and out[1:] == [3, {"k": "v"}]


def test_mask_failure_sends_the_payload(monkeypatch):
    def boom():
        raise RuntimeError

    monkeypatch.setattr(tracing, "masking_enabled", boom)
    assert tracing.mask_payload(data="raw") == "raw"


# --- export filter, flush, configure -------------------------------------------

def test_export_drops_empty_hooks(monkeypatch):
    sf = types.ModuleType("langfuse.span_filter")
    sf.is_default_export_span = lambda span: True
    monkeypatch.setitem(sys.modules, "langfuse.span_filter", sf)
    assert tracing.export_span(SimpleNamespace(name="model")) is True
    assert tracing.export_span(SimpleNamespace(name="sql_retry_limiter.before_model")) is False
    assert tracing.export_span(SimpleNamespace(name=None)) is True


def test_flush_calls_the_client_and_swallows_errors(monkeypatch):
    flushed = []
    _install(monkeypatch, get_client=lambda: SimpleNamespace(flush=lambda: flushed.append(1)))
    tracing.flush_traces()
    assert flushed == [1]

    def broken():
        raise RuntimeError("down")

    _install(monkeypatch, get_client=broken)
    tracing.flush_traces()  # does not raise


def test_configure_is_off_without_keys():
    assert tracing.configure_langfuse(Settings(langfuse_public_key="", langfuse_secret_key="")) is False


def test_configure_passes_vercel_env_and_succeeds(monkeypatch):
    seen = {}

    class Client:
        _mask = staticmethod(tracing.mask_payload)

        def auth_check(self):
            return True

    def build(**kwargs):
        seen.update(kwargs)
        return Client()

    monkeypatch.delenv("LANGFUSE_TRACING_ENVIRONMENT", raising=False)
    monkeypatch.delenv("LANGFUSE_RELEASE", raising=False)
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "abc123")
    _install(monkeypatch, Langfuse=build)
    assert tracing.configure_langfuse(Settings(**ENABLED)) is True
    assert seen["environment"] == "production" and seen["release"] == "abc123"
    assert seen["mask"] is tracing.mask_payload


def test_configure_refuses_a_client_built_without_the_mask(monkeypatch, caplog):
    _install(monkeypatch, Langfuse=lambda **k: SimpleNamespace(_mask=None))
    with caplog.at_level("ERROR"):
        assert tracing.configure_langfuse(Settings(**ENABLED)) is False
    assert "without a mask" in caplog.text


def test_configure_reports_rejected_credentials(monkeypatch, caplog):
    client = SimpleNamespace(_mask=tracing.mask_payload, auth_check=lambda: False)
    _install(monkeypatch, Langfuse=lambda **k: client)
    with caplog.at_level("ERROR"):
        assert tracing.configure_langfuse(Settings(**ENABLED)) is False
    assert "credentials rejected" in caplog.text


def test_configure_survives_a_broken_sdk(monkeypatch):
    def broken(**k):
        raise ImportError("no sdk")

    _install(monkeypatch, Langfuse=broken)
    assert tracing.configure_langfuse(Settings(**ENABLED)) is False


# --- current observation and scores ------------------------------------------

def test_current_observation_finds_our_handler_run():
    from langchain_core.runnables.config import var_child_runnable_config

    ours = SimpleNamespace(_node_runs={}, _runs={"p1": "obs"})
    manager = SimpleNamespace(parent_run_id="p1", handlers=[SimpleNamespace(), ours])
    token = var_child_runnable_config.set({"callbacks": manager})
    try:
        assert tracing.current_observation() == "obs"
        manager.handlers = [SimpleNamespace()]
        assert tracing.current_observation() is None
    finally:
        var_child_runnable_config.reset(token)
    assert tracing.current_observation() is None


def test_score_goes_to_the_current_run_or_the_client(monkeypatch):
    scored = []
    run = SimpleNamespace(score_trace=lambda **kw: scored.append(("run", kw)))
    client = SimpleNamespace(score_current_trace=lambda **kw: scored.append(("client", kw)))
    _install(monkeypatch, get_client=lambda: client)
    monkeypatch.setattr(tracing, "current_observation", lambda: run)
    tracing.score_answer("a", 1.0, "c")
    monkeypatch.setattr(tracing, "current_observation", lambda: None)
    tracing.score_answer("b", 0.0)
    assert scored == [("run", {"name": "a", "value": 1.0, "comment": "c"}),
                      ("client", {"name": "b", "value": 0.0, "comment": None})]

    def broken():
        raise RuntimeError

    monkeypatch.setattr(tracing, "current_observation", broken)
    tracing.score_answer("c", 1.0)  # swallowed


# --- shaping root input/output -----------------------------------------------

def test_observation_type():
    assert tracing.observation_type("x", is_root=True, metadata=None) == "agent"
    assert tracing.observation_type("researcher", is_root=False, metadata={"lc_agent_name": "researcher"}) == "agent"
    assert tracing.observation_type(tracing.AUDIT_HOOK, is_root=False, metadata=None) == "evaluator"
    assert tracing.observation_type("model", is_root=False, metadata={}) == "chain"


def test_root_input_is_the_last_question():
    state = {"messages": [{"role": "user", "content": "first"}, AIMessage("a"),
                          HumanMessage(content=[{"type": "text", "text": "second"}, {"type": "image"}])]}
    assert tracing.root_input(state) == "second"
    assert tracing.root_input("raw") == "raw"
    assert tracing.root_input({"messages": [{"role": "user", "content": None}]}) == ""


def test_root_output_is_the_replies_after_the_last_question():
    state = {"messages": [HumanMessage("q"), AIMessage("", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
                          ToolMessage("r", tool_call_id="1"), AIMessage("part one"),
                          {"role": "assistant", "content": "part two"}]}
    assert tracing.root_output(state) == "part one\n\npart two"


def test_root_output_names_a_pending_approval():
    state = {"messages": [HumanMessage("q"), AIMessage("Planning"),
                          {"type": "ai", "content": "", "tool_calls": [{"name": "run_import_now", "args": {"n": 2}}]}]}
    assert tracing.root_output(state) == 'Planning\n\nWaiting for a person to approve: run_import_now({"n": 2})'


def test_root_output_prefers_a_structured_response():
    model = SimpleNamespace(model_dump=lambda: {"ok": True})
    assert tracing.root_output({"structured_response": model}) == {"ok": True}
    assert tracing.root_output({"structured_response": {"x": 1}}) == {"x": 1}
    assert tracing.root_output({"messages": []}) == {"messages": []}


# --- the handler -------------------------------------------------------------

@pytest.fixture
def handler(monkeypatch):
    calls = []

    class CallbackHandler:
        def __init__(self, **kwargs):
            self._runs = {}

        def get_langchain_run_name(self, serialized, **kwargs):
            return kwargs.get("name") or serialized.get("name")

        def _get_observation_type_from_serialized(self, serialized, callback_type, **kwargs):
            return "sdk-guess"

        def _detach_observation(self, run_id):
            return None

    def recorder(attr):
        return lambda self, *a, **kw: calls.append((attr, a, kw))

    for attr in ("on_chain_start", "on_chat_model_start", "on_llm_start", "on_tool_start", "on_chain_end",
                 "on_tool_end", "on_chain_error"):
        setattr(CallbackHandler, attr, recorder(attr))

    sub = types.ModuleType("langfuse.langchain")
    sub.CallbackHandler = CallbackHandler
    _install(monkeypatch, langchain=sub)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", sub)
    h = tracing._build_handler(Settings(**ENABLED))
    h.calls = calls
    return h


def test_root_chain_gets_the_question_and_is_an_agent(handler):
    handler.on_chain_start({"name": "sangam_ask"}, {"messages": [HumanMessage("hi")]}, run_id="r0")
    name, args, kw = handler.calls[-1]
    assert name == "on_chain_start" and args[1] == "hi" and kw["sangam_type"] == "agent"


def test_a_node_run_becomes_the_parent_of_orphans(handler):
    meta = {"langgraph_node": "model", "langgraph_checkpoint_ns": "model:1"}
    handler._runs["root"] = object()
    handler.on_chain_start({"name": "model"}, {}, run_id="n1", parent_run_id="root", metadata=meta)
    assert handler.calls[-1][2]["parent_run_id"] == "root" and handler._node_runs == {"model:1": "n1"}

    orphan_meta = {"langgraph_checkpoint_ns": "model:1"}
    handler.on_chat_model_start({}, [], run_id="m1", parent_run_id="langsmith-only", metadata=orphan_meta)
    handler.on_llm_start({}, [], run_id="m2", parent_run_id="langsmith-only", metadata=orphan_meta)
    handler.on_tool_start({}, "x", run_id="t1", parent_run_id="unknown", metadata={})
    parents = [c[2]["parent_run_id"] for c in handler.calls[-3:]]
    assert parents == ["n1", "n1", "unknown"]

    handler.on_chain_end({"x": 1}, run_id="n1", parent_run_id="root")
    assert handler._node_runs == {} and handler.calls[-1][1] == ({"x": 1},)


def test_root_end_carries_the_answer(handler):
    handler.on_chain_end({"messages": [HumanMessage("q"), AIMessage("a")]}, run_id="r0")
    assert handler.calls[-1][1] == ("a",)


def test_observation_type_uses_ours_or_the_sdks(handler):
    assert handler._get_observation_type_from_serialized({}, "chain", sangam_type="agent") == "agent"
    assert handler._get_observation_type_from_serialized({}, "chain") == "sdk-guess"


def test_tool_end_redacts_rows_when_masking(handler, monkeypatch):
    monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "1")
    handler.on_tool_end("1 row(s)\ncolumns: id\n1", run_id="t")
    assert handler.calls[-1][1][0].endswith("[1 row(s) redacted: LANGFUSE_MASK_TOOL_RESULTS is on]")
    handler.on_tool_end(SimpleNamespace(content=7), run_id="t")
    assert handler.calls[-1][1][0].content == 7


def test_tool_end_redaction_failure_passes_output_through(handler, monkeypatch):
    monkeypatch.setenv("LANGFUSE_MASK_TOOL_RESULTS", "1")

    def boom(text):
        raise RuntimeError

    monkeypatch.setattr(tracing, "_redact_rows", boom)
    handler.on_tool_end("columns: id\n1", run_id="t")
    assert handler.calls[-1][1][0] == "columns: id\n1"


def test_chain_error_cancelled_without_an_observation_and_real_errors(handler):
    assert handler.on_chain_error(asyncio.CancelledError(), run_id="r") is None
    handler.on_chain_error(ValueError("x"), run_id="r")
    assert handler.calls[-1][0] == "on_chain_error"


def test_trace_config_degrades_when_the_handler_fails(monkeypatch):
    def broken(settings):
        raise RuntimeError("bad")

    monkeypatch.setattr(tracing, "_build_handler", broken)
    assert tracing.trace_config(Settings(**ENABLED), name="n") == {"run_name": "n"}


# --- AG-UI agent pieces ------------------------------------------------------

async def test_run_flushes_even_when_the_stream_fails(monkeypatch):
    from copilotkit import LangGraphAGUIAgent

    flushed = []

    async def stream(self, input):
        yield "e1"
        raise RuntimeError("stream broke")

    monkeypatch.setattr(LangGraphAGUIAgent, "run", stream)
    monkeypatch.setattr(tracing, "flush_traces", lambda: flushed.append(1))
    agent = object.__new__(tracing.SessionScopedAGUIAgent)
    agent.graph = object()
    seen = []
    with pytest.raises(RuntimeError):
        async for event in agent.run(RunAgentInput(thread_id="t", run_id="r", messages=[])):
            seen.append(event)
    assert seen == ["e1"] and flushed == [1]


def test_collect_interrupts_skips_answered_tasks():
    tasks = [SimpleNamespace(result=None, interrupts=["i1", "i2"]), SimpleNamespace(result="done", interrupts=["x"]),
             SimpleNamespace(result=None, interrupts=None)]
    assert tracing.SessionScopedAGUIAgent._collect_interrupts(tasks) == ["i1", "i2"]
    assert tracing.SessionScopedAGUIAgent._collect_interrupts(None) == []


def test_merge_state_drops_tool_results_already_answered(monkeypatch):
    from copilotkit import LangGraphAGUIAgent

    captured = {}
    monkeypatch.setattr(LangGraphAGUIAgent, "langgraph_default_merge_state",
                        lambda self, state, messages, input: captured.setdefault("m", messages))
    agent = object.__new__(tracing.SessionScopedAGUIAgent)
    state = {"messages": [ToolMessage("done", tool_call_id="a")]}
    incoming = [ToolMessage("again", tool_call_id="a"), ToolMessage("new", tool_call_id="b"), HumanMessage("q")]
    agent.langgraph_default_merge_state(state, incoming, None)
    assert [getattr(m, "tool_call_id", None) for m in captured["m"]] == ["b", None]


def test_key_resume_passes_bad_json_through():
    assert tracing.key_resume("not json", []) == "not json"


# --- sql spans ---------------------------------------------------------------

def test_sql_span_yields_none_when_it_cannot_start(monkeypatch):
    def broken():
        raise RuntimeError

    _install(monkeypatch, get_client=broken)
    monkeypatch.setattr(tracing, "current_observation", lambda: None)
    with tracing.sql_span("q", "SELECT 1") as span:
        assert span is None


@pytest.mark.parametrize("env, expected", [
    ({"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "k", "LANGSMITH_PROJECT": "p"}, "enabled: project=p"),
    ({"LANGSMITH_TRACING": "true"}, "will be DROPPED"),
    ({"LANGCHAIN_API_KEY": "k"}, "tracing is OFF"),
    ({}, "LangSmith tracing disabled"),
])
def test_langsmith_status(monkeypatch, env, expected):
    for var in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert expected in tracing.langsmith_status()

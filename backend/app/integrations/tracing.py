"""Langfuse tracing wiring."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import AbstractContextManager, contextmanager, nullcontext
from textwrap import dedent
from typing import Any

from ag_ui.core.types import RunAgentInput
from copilotkit import LangGraphAGUIAgent
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from app.core.config import Settings
from app.core.security import DEV_USER_ID, CallerScope, chat_proposal, chat_scope, chat_user_id

logger = logging.getLogger(__name__)

# Names the root span, and so the trace, once update_trace=True is set.
TRACE_NAME = "sangam_agent"

# Traces are for debugging, not archival. Anything longer than this is a result
# grid or a document, and neither is readable in a trace viewer anyway.
MAX_IO_CHARS = 4_000

# Where row data begins in a tool result. Everything BEFORE these markers describes the query and is what
# you actually read a trace for; everything after is warehouse rows.
_GRID_HEADER = "columns: "          # db_query, from render_rows()
_PROFILE_HEADER = "as stored:"      # db_profile_column

# Middleware hooks run as graph nodes, one set per model call. These never call a model, so they
# are empty leaves and safe to drop; an unlisted hook stays, since dropping a parent orphans children.
_EMPTY_HOOK = re.compile(
    r"^(PatchToolCallsMiddleware|SkillsMiddleware|sql_retry_limiter|RunSources|DropFilesOnExit)"
    r"\.(before|after)_(agent|model)$"
)
AUDIT_HOOK = "answer_audit.after_agent"


def masking_enabled() -> bool:
    """Whether to redact query results from the tool spans in a trace."""
    return os.getenv("LANGFUSE_MASK_TOOL_RESULTS", "").lower() in ("1", "true", "yes")


def _redact_rows(text: str) -> str:
    """Stub the data rows of a rendered result, leaving the query intact."""
    lines = text.split("\n")
    cut = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(_GRID_HEADER) or stripped.endswith(_PROFILE_HEADER):
            cut = i + 1
            break
    if cut is None or cut >= len(lines):
        return text

    kept = lines[:cut]
    redacted = sum(1 for line in lines[cut:] if line.strip())
    if not redacted:
        return text
    kept.append(f"[{redacted} row(s) redacted: LANGFUSE_MASK_TOOL_RESULTS is on]")
    return "\n".join(kept)


def mask_payload(*, data: Any, **_: Any) -> Any:
    """Langfuse v3 mask hook: runs over every input/output before it is sent."""
    try:
        if isinstance(data, str):
            text = _redact_rows(data) if masking_enabled() else data
            return text[:MAX_IO_CHARS] if len(text) > MAX_IO_CHARS else text
        if isinstance(data, dict):
            return {k: mask_payload(data=v) for k, v in data.items()}
        if isinstance(data, list):
            return [mask_payload(data=v) for v in data]
        return data
    except Exception:
        logger.debug("mask failed; sending the payload unmasked", exc_info=True)
        return data


def export_span(span: Any) -> bool:
    """v4's default filter (drops FastAPI's HTTP spans), minus hooks that record nothing."""
    from langfuse.span_filter import is_default_export_span

    return is_default_export_span(span) and not _EMPTY_HOOK.match(span.name or "")


def flush_traces() -> None:
    """Send what is buffered: a serverless function freezes once it has answered."""
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        logger.debug("Langfuse flush failed", exc_info=True)


def configure_langfuse(settings: Settings) -> bool:
    """Build the Langfuse client once, with masking and clipping attached."""
    if not settings.langfuse_enabled:
        return False
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_host,
            mask=mask_payload,
            should_export_span=export_span,
            # Vercel sets these, so a deployed trace is filed under its environment and commit
            # without anyone remembering LANGFUSE_TRACING_ENVIRONMENT / LANGFUSE_RELEASE.
            environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT") or os.getenv("VERCEL_ENV"),
            release=os.getenv("LANGFUSE_RELEASE") or os.getenv("VERCEL_GIT_COMMIT_SHA"),
        )
        # Resources are shared per public key and the FIRST construction wins, so a client
        # built before this leaves masking silently off. Verified, not assumed.
        if getattr(client, "_mask", None) is not mask_payload:
            logger.error(
                "Langfuse client was already built without a mask; query results "
                "WILL appear in traces. Ensure configure_langfuse() runs before "
                "anything else touches langfuse."
            )
            return False

        # Wrong keys for this host fail silently: spans are exported on a
        # background thread and rejected with a 401 nobody reads.
        try:
            if not client.auth_check():
                raise ValueError("credentials rejected")
        except Exception as exc:  # noqa: BLE001 - any failure here means traces are lost
            logger.error(
                "Langfuse credentials are not valid for %s (%s). Traces will be DROPPED — "
                "check LANGFUSE_HOST matches the instance the keys belong to.",
                settings.langfuse_host,
                exc,
            )
            return False
        return True
    except Exception:  # telemetry must never take the app down
        logger.warning("Langfuse client could not be built — continuing untraced", exc_info=True)
        return False


def current_observation() -> Any:
    """The handler's observation for the LangChain run executing now; v4 puts none on the OTel context."""
    from langchain_core.runnables.config import var_child_runnable_config

    manager = (var_child_runnable_config.get() or {}).get("callbacks")
    run_id = getattr(manager, "parent_run_id", None)
    for handler in getattr(manager, "handlers", None) or ():
        if hasattr(handler, "_node_runs"):  # ours: the class is built inside _build_handler
            return handler._runs.get(run_id)
    return None


def score_answer(name: str, value: float, comment: str | None = None) -> None:
    """Attach a score to the trace of the turn being handled."""
    try:
        from langfuse import get_client

        run = current_observation()
        if run is not None:
            run.score_trace(name=name, value=value, comment=comment)
        else:
            get_client().score_current_trace(name=name, value=value, comment=comment)
    except Exception:
        logger.debug("could not attach score %r", name, exc_info=True)



def observation_type(name: str, *, is_root: bool, metadata: dict | None) -> str:
    """The graph and each subagent are agents; the audit hook is an evaluator; the rest are chains."""
    if is_root or name == (metadata or {}).get("lc_agent_name"):
        return "agent"
    if name == AUDIT_HOOK:
        return "evaluator"
    return "chain"


def _messages(state: Any) -> list[Any]:
    return (state.get("messages") or []) if isinstance(state, dict) else []


def _role(message: Any) -> str | None:
    return message.get("type") or message.get("role") if isinstance(message, dict) else getattr(message, "type", None)


def _text(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    blocks = content if isinstance(content, list) else []
    return "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")


def root_input(inputs: Any) -> Any:
    """The question asked, not the whole conversation state: it is what the trace list shows."""
    asked = [m for m in _messages(inputs) if _role(m) in ("human", "user")]
    return _text(asked[-1]) if asked else inputs


def root_output(outputs: Any) -> Any:
    """What the person was shown this turn: the replies after their last message that call no tool."""
    # An agent with a response_format answers in its structured result, e.g. the news verifier's check.
    structured = outputs.get("structured_response") if isinstance(outputs, dict) else None
    if structured is not None:
        return structured.model_dump() if hasattr(structured, "model_dump") else structured
    messages = _messages(outputs)
    last_asked = max((i for i, m in enumerate(messages) if _role(m) in ("human", "user")), default=-1)
    replies = [
        _text(m) for m in messages[last_asked + 1:]
        if _role(m) in ("ai", "assistant")
        and not (m.get("tool_calls") if isinstance(m, dict) else getattr(m, "tool_calls", None))
    ]
    answer = "\n\n".join(r for r in replies if r.strip())
    # A turn that stopped for approval ends on tool calls nobody answered, e.g. run_import_now's card.
    last = messages[-1] if messages else None
    calls = (last.get("tool_calls") if isinstance(last, dict) else getattr(last, "tool_calls", None)) or []
    if _role(last) in ("ai", "assistant") and calls:
        waiting = ", ".join(f"{c.get('name')}({json.dumps(c.get('args', {}), default=str)})" for c in calls)
        return f"{answer}\n\nWaiting for a person to approve: {waiting}".strip()
    return answer or outputs


def _build_handler(settings: Settings):
    """The LangChain handler, bound to the client configure_langfuse() built."""
    from langfuse.langchain import CallbackHandler

    class _CancellationTolerantHandler(CallbackHandler):
        """Treats a cancelled turn as control flow, not an error."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            # Graph node run per LangGraph task: the fallback parent for a run whose own parent this
            # handler never saw (LangSmith's tracer wraps model calls in runs no callback receives).
            self._node_runs: dict[str, Any] = {}

        def _known_parent(self, parent_run_id, metadata):
            if parent_run_id is None or parent_run_id in self._runs:
                return parent_run_id
            return self._node_runs.get((metadata or {}).get("langgraph_checkpoint_ns"), parent_run_id)

        def _forget(self, run_id):
            for ns, node_run in list(self._node_runs.items()):
                if node_run == run_id:
                    del self._node_runs[ns]

        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kwargs):
            name = self.get_langchain_run_name(serialized, **kwargs)
            kind = observation_type(name, is_root=parent_run_id is None, metadata=metadata)
            if parent_run_id is None:
                inputs = root_input(inputs)
            if metadata and metadata.get("langgraph_node") == name and metadata.get("langgraph_checkpoint_ns"):
                self._node_runs[metadata["langgraph_checkpoint_ns"]] = run_id
            return super().on_chain_start(
                serialized, inputs, run_id=run_id, parent_run_id=self._known_parent(parent_run_id, metadata),
                metadata=metadata, sangam_type=kind, **kwargs,
            )

        def _get_observation_type_from_serialized(self, serialized, callback_type, **kwargs):
            # The SDK's guess is "agent" for any name containing it, so a hook was an agent and the
            # agents themselves chains.
            return kwargs.get("sangam_type") or super()._get_observation_type_from_serialized(
                serialized, callback_type, **kwargs
            )

        def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, **kwargs):
            return super().on_chat_model_start(
                serialized, messages, run_id=run_id, parent_run_id=self._known_parent(parent_run_id, metadata),
                metadata=metadata, **kwargs,
            )

        def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, metadata=None, **kwargs):
            return super().on_llm_start(
                serialized, prompts, run_id=run_id, parent_run_id=self._known_parent(parent_run_id, metadata),
                metadata=metadata, **kwargs,
            )

        def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, metadata=None, **kwargs):
            return super().on_tool_start(
                serialized, input_str, run_id=run_id, parent_run_id=self._known_parent(parent_run_id, metadata),
                metadata=metadata, **kwargs,
            )

        def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
            self._forget(run_id)
            if parent_run_id is None:
                outputs = root_output(outputs)
            return super().on_chain_end(outputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

        def on_tool_end(self, output, *, run_id, **kwargs):
            """Redact query results here, not via the client `mask` hook."""
            if masking_enabled():
                try:
                    text = output if isinstance(output, str) else getattr(output, "content", None)
                    if isinstance(text, str):
                        output = _redact_rows(text)
                except Exception:  # never fail a turn over telemetry
                    logger.debug("tool-output redaction failed", exc_info=True)
            return super().on_tool_end(output, run_id=run_id, **kwargs)

        def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
            self._forget(run_id)
            if isinstance(error, asyncio.CancelledError):
                # Same shape the SDK uses for control flow: end the observation
                # without an ERROR level.
                observation = self._detach_observation(run_id)
                if observation is not None:
                    observation.update(status_message="cancelled: client disconnected").end()
                return None
            return super().on_chain_error(
                error, run_id=run_id, parent_run_id=parent_run_id, **kwargs
            )

    return _CancellationTolerantHandler(public_key=settings.langfuse_public_key)


def trace_config(
    settings: Settings, *, name: str = TRACE_NAME, tags: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Config fragment attaching Langfuse to the agent graph.

    `name` is what a trace is called in Langfuse. Every agent passes its own:
    two graphs sharing one name makes the two indistinguishable in the UI, and
    a run's name is the only thing shown before you open it.
    """
    base: dict[str, Any] = {"run_name": name}
    if not settings.langfuse_enabled:
        return base
    try:
        return {
            **base,
            "callbacks": [_build_handler(settings)],
            "metadata": {"langfuse_trace_name": name, "langfuse_tags": ["sangam", *tags, settings.model]},
        }
    except Exception:  # telemetry must never take the app down
        logger.warning(
            "Langfuse keys are set but tracing could not be enabled — continuing without it",
            exc_info=True,
        )
        return base


def caller_trace(scope: CallerScope | None, user_id: Any) -> tuple[str, list[str], dict[str, Any]]:
    """Who asked, for Langfuse: the email as its user, and their orgs as tags to filter by."""
    if scope is None:
        return str(user_id or DEV_USER_ID), [], {}
    tags = ["role:staff"] if scope.is_staff else []
    tags += sorted({f"role:{role}" for role in scope.org_roles.values()})
    tags += sorted(f"org:{scope.org_names.get(org, org)}" for org in scope.org_roles)
    metadata = {"sangam_user_id": str(scope.user_id), "org_roles": {str(o): r for o, r in scope.org_roles.items()}}
    return scope.email or str(scope.user_id or DEV_USER_ID), tags, metadata


def propagate_caller(config: dict[str, Any] | None, session_id: str | None = None) -> AbstractContextManager:
    """Puts the caller on every span inside: v4 dashboards read user and tags per observation, not per trace."""
    try:
        from langfuse import propagate_attributes

        user, tags, _ = caller_trace(chat_scope.get(), chat_user_id.get())
        meta = (config or {}).get("metadata") or {}
        return propagate_attributes(
            user_id=user, session_id=session_id, trace_name=meta.get("langfuse_trace_name"),
            tags=[*meta.get("langfuse_tags", ()), *tags],
        )
    except Exception:  # telemetry must never take the app down
        logger.debug("Langfuse attributes not propagated", exc_info=True)
        return nullcontext()


class SessionScopedAGUIAgent(LangGraphAGUIAgent):
    """AG-UI agent that tags each run with the conversation it belongs to."""

    def __init__(
        self,
        *,
        name: str,
        graph: Any,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        emit_subagent_events: bool = False,
        emit_raw_events: bool = True,
    ) -> None:
        super().__init__(name=name, graph=graph, description=description, config=config)
        # copilotkit's __init__ drops these flags, so they are set here; clone() passes them back per request.
        self.emit_subagent_events = emit_subagent_events
        self.subagent_visibility = "attributed" if emit_subagent_events else "inline"
        self.emit_raw_events = emit_raw_events

    async def run(self, input: RunAgentInput):
        try:
            with propagate_caller(getattr(self.graph, "config", None), input.thread_id):
                async for event in super().run(input):
                    yield event
        finally:
            await asyncio.to_thread(flush_traces)


    @staticmethod
    def _collect_interrupts(tasks) -> list:
        # A task answered while its siblings stay paused keeps its interrupt, with a result beside it.
        return [i for t in tasks or () if getattr(t, "result", None) is None for i in getattr(t, "interrupts", ()) or ()]

    def langgraph_default_merge_state(self, state, messages, input):
        # The browser re-sends tool results under its own ids, so the library's id dedup appends them twice.
        answered = {
            m.tool_call_id for m in state.get("messages", [])
            if isinstance(m, ToolMessage)
            and not (isinstance(m.content, str) and self._ORPHAN_TOOL_MSG_RE.match(m.content))
        }
        messages = [m for m in messages if not (isinstance(m, ToolMessage) and m.tool_call_id in answered)]
        return super().langgraph_default_merge_state(state, messages, input)

    async def prepare_stream(
        self,
        input: RunAgentInput,
        agent_state: dict[str, Any],
        config: RunnableConfig,
    ):
        user, tags, caller = caller_trace(chat_scope.get(), chat_user_id.get())
        if (proposal_id := chat_proposal.get()) is not None:
            caller["proposal_id"] = proposal_id
        config = {
            **config,
            # LangChain unions these, and Langfuse adds them to the graph's own langfuse_tags.
            "tags": [*(config.get("tags") or []), *tags],
            "metadata": {
                **(config.get("metadata") or {}),
                **caller,
                "langfuse_session_id": input.thread_id,
                "langfuse_user_id": user,
                # Request context, per Langfuse's metadata guidance: lets a
                # trace be tied back to the AG-UI run that produced it.
                "agui_run_id": input.run_id,
            },
        }
        command = (input.forwarded_props or {}).get("command")
        if isinstance(command, dict) and command.get("resume") is not None:
            keyed = key_resume(command["resume"], self._collect_interrupts(agent_state.tasks))
            input = input.model_copy(update={"forwarded_props": {
                **input.forwarded_props, "command": {**command, "resume": keyed}}})
        return await super().prepare_stream(
            input=input, agent_state=agent_state, config=config
        )


def _slugs(value: Any) -> set[str]:
    actions = value.get("action_requests") if isinstance(value, dict) else None
    return {(a.get("args") or {}).get("slug") for a in actions or () if isinstance(a, dict)} - {None}


def key_resume(resume: Any, interrupts: list[Any]) -> Any:
    """Address a legacy resume to one open interrupt: parallel Import writers pause together, and LangGraph
    refuses an unaddressed resume. It goes to the save its slug names, else the last one the screen saw."""
    if isinstance(resume, str):
        try:
            resume = json.loads(resume)
        except json.JSONDecodeError:
            return resume
    slug = None
    if isinstance(resume, dict) and "slug" in resume:
        resume = dict(resume)
        slug = resume.pop("slug")
    if not interrupts or (isinstance(resume, dict) and any(i.id in resume for i in interrupts)):
        return resume
    target = next((i for i in interrupts if slug and slug in _slugs(i.value)), interrupts[-1])
    return {target.id: resume}


@contextmanager
def sql_span(name: str, sql: str, params: Any = None):
    """Record one SQL statement as a child of the span that is current."""
    try:
        from langfuse import get_client

        parent = current_observation() or get_client()
        cm = parent.start_as_current_observation(
            name=name,
            as_type="retriever",
            input={"sql": dedent(sql).strip(), "params": params},
        )
    except Exception:  # never fail a query over telemetry
        logger.debug("SQL span could not be started", exc_info=True)
        yield None
        return

    with cm as span:
        yield span


async def traced_fetch(
    conn: Any,
    sql: str,
    params: Any = None,
    *,
    name: str,
    prepare: bool | None = None,
) -> list[Any]:
    """`conn.execute(...).fetchall()`, with the statement recorded on the trace."""
    with sql_span(name, sql, params) as span:
        kwargs = {} if prepare is None else {"prepare": prepare}
        rows = await (await conn.execute(sql, params, **kwargs)).fetchall()
        if span is not None:
            span.update(output={"row_count": len(rows)})
        return rows


def langsmith_status() -> str:
    """One line on whether LangSmith will receive anything, for the boot log.

    LangSmith needs no wiring in a LangGraph app — the tracer is switched on by
    environment variables alone, and the `run_name` each agent already sets
    names the root run there too. What it does need is for someone to be told
    when it is silently off, which is the failure that cost a day with Langfuse.
    """
    enabled = os.environ.get("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")
    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    project = os.environ.get("LANGSMITH_PROJECT", "default")
    if enabled and key:
        return f"LangSmith tracing enabled: project={project}"
    if enabled and not key:
        return "LangSmith TRACING=true but no LANGSMITH_API_KEY — traces will be DROPPED"
    if key and not enabled:
        return "LangSmith key is set but LANGSMITH_TRACING is not true — tracing is OFF"
    return "LangSmith tracing disabled (set LANGSMITH_TRACING=true and LANGSMITH_API_KEY)"

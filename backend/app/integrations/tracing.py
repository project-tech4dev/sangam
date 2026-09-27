"""Langfuse tracing wiring.

Two things make a trace readable in the Langfuse UI, and neither is on by
default:

  - The root span has to carry a name, the question, and the answer. The
    LangChain handler only does that when built with `update_trace=True`;
    without it every trace is called "LangGraph" and its input/output are
    empty, so the trace list is unreadable and you must open a nested span to
    see anything.
  - Turns have to be linked. The handler groups by `metadata.langfuse_session_id`
    and ignores LangGraph's `thread_id` entirely, so a six-turn conversation
    arrives as six unrelated traces until something maps one to the other.

Everything here follows the "optional subsystems degrade, they do not crash"
rule: tracing that cannot start logs loudly and the app runs untraced.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from textwrap import dedent
from typing import Any

from ag_ui.core.types import RunAgentInput
from copilotkit import LangGraphAGUIAgent
from langchain_core.runnables import RunnableConfig

from app.core.config import Settings
from app.core.security import DEV_USER_ID

logger = logging.getLogger(__name__)

# Names the root span, and so the trace, once update_trace=True is set.
TRACE_NAME = "sangam_agent"

# Traces are for debugging, not archival. Anything longer than this is a result
# grid or a document, and neither is readable in a trace viewer anyway.
MAX_IO_CHARS = 4_000

# Where row data begins in a tool result. Everything BEFORE these markers
# describes the query and is what you actually read a trace for; everything
# after is warehouse rows.
_GRID_HEADER = "columns: "          # db_query, from render_rows()
_PROFILE_HEADER = "as stored:"      # db_profile_column


def masking_enabled() -> bool:
    """Whether to redact query results from the tool spans in a trace.

    Tool outputs carry real rows — org records, contact names, grant amounts —
    and this keeps them out of the db_query span, which is where a whole result
    grid lands in one place. The SQL, the tool inputs and the row counts are
    still recorded, which is what you actually debug with.

    It is a reduction, NOT a guarantee, and the difference matters. Those rows
    are fed back to the model, so they also appear in the generation inputs and
    in the LangGraph state carried on chain spans, and masking those would mean
    rewriting every payload the handler emits. Langfuse's own client-level
    `mask` hook does not close the gap: it is invoked for the tool output and
    the stored observation still held every row — verified against a live trace
    before this callback-level redaction was written.

    So the real control is WHERE Langfuse runs. A trace of this agent belongs on
    an instance inside your own deployment, not a cloud project the cohort has
    not consented to. (Dalgo's implementation masks at exactly the same single
    point and their docs say the same thing.)
    """
    return os.getenv("LANGFUSE_MASK_TOOL_RESULTS", "").lower() in ("1", "true", "yes")


def _redact_rows(text: str) -> str:
    """Stub the data rows of a rendered result, leaving the query intact.

    Only fires on payloads that actually have the shape of a result — a
    `columns:` grid header or a profile's `as stored:` header. An earlier
    version redacted every line that did not look like metadata, which quietly
    destroyed the SQL in sql_span's input: a bare "SELECT 1" is not metadata,
    so it was replaced by the redaction stub. Recognising the data rather than
    guessing at the not-data is the difference.
    """
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
    """Langfuse v3 mask hook: runs over every input/output before it is sent.

    Applied at the client, so it covers observations the LangChain handler
    creates as well as our own spans — there is no per-call-site to forget.
    Never raises: a mask that throws would drop the whole batch.
    """
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


def configure_langfuse(settings: Settings) -> bool:
    """Build the Langfuse client once, with masking and clipping attached.

    Must run before any CallbackHandler is created. v3 shares resources per
    public key, so constructing the client here is what puts `mask` in front of
    every observation the LangChain handler later produces — passing it to the
    handler is not possible, and setting it afterwards is too late.
    """
    if not settings.langfuse_enabled:
        return False
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            mask=mask_payload,
            # environment and release are read from LANGFUSE_TRACING_ENVIRONMENT
            # and LANGFUSE_RELEASE by the SDK itself.
        )
        # v3 shares resources per public key and the FIRST construction wins, so
        # if anything built a client before this the mask is silently absent —
        # and silently absent masking sends warehouse rows to the trace backend.
        # Verified rather than assumed.
        if getattr(client, "_mask", None) is not mask_payload:
            logger.error(
                "Langfuse client was already built without a mask; query results "
                "WILL appear in traces. Ensure configure_langfuse() runs before "
                "anything else touches langfuse."
            )
            return False
        return True
    except Exception:  # telemetry must never take the app down
        logger.warning("Langfuse client could not be built — continuing untraced", exc_info=True)
        return False


def score_answer(name: str, value: float, comment: str | None = None) -> None:
    """Attach a score to the trace of the turn being handled.

    What makes the post-answer audit visible in Langfuse's evaluation views
    rather than only in the chat. Fail-open and silent: a score is never worth
    a failed turn, and there is no trace to score when tracing is off.
    """
    try:
        from langfuse import get_client

        get_client().score_current_trace(name=name, value=value, comment=comment)
    except Exception:
        logger.debug("could not attach score %r", name, exc_info=True)



def _build_handler(settings: Settings):
    """The LangChain handler, bound to the client configure_langfuse() built.

    Passing public_key is what binds it: v3 resolves the handler's client by
    key, and the one registered under ours carries the mask. Without it the
    handler builds its own client from the environment and every payload goes
    out unmasked.
    """
    from langfuse.langchain import CallbackHandler

    class _CancellationTolerantHandler(CallbackHandler):
        """Treats a cancelled turn as control flow, not an error.

        A browser disconnect or a redeploy cancels the streaming task mid-turn,
        which surfaces here as asyncio.CancelledError. The SDK already exempts
        LangGraph's GraphBubbleUp but not this, so every disconnected user was
        about to become an ERROR trace and an inflated error rate.
        """

        def on_tool_end(self, output, *, run_id, **kwargs):
            """Redact query results here, not via the client `mask` hook.

            The v3 client takes a `mask` callable and it does run — but not on
            the output the LangChain handler records for a tool span, which is
            the one payload that carries warehouse rows. Verified against a live
            trace: the mask was invoked with exactly this string and the stored
            observation still held every org name. Masking at the callback is
            the only place that actually covers it, which is also where the
            Dalgo implementation does it.
            """
            if masking_enabled():
                try:
                    text = output if isinstance(output, str) else getattr(output, "content", None)
                    if isinstance(text, str):
                        output = _redact_rows(text)
                except Exception:  # never fail a turn over telemetry
                    logger.debug("tool-output redaction failed", exc_info=True)
            return super().on_tool_end(output, run_id=run_id, **kwargs)

        def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
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

    # update_trace lifts name/input/output/metadata from the root chain onto
    # the trace itself — without it the trace list shows nothing.
    return _CancellationTolerantHandler(
        public_key=settings.langfuse_public_key, update_trace=True
    )


def trace_config(settings: Settings) -> dict[str, Any]:
    """Config fragment attaching Langfuse to the agent graph.

    Returns the run name alone when tracing is off, so the graph is named
    consistently whether or not Langfuse is configured.
    """
    base: dict[str, Any] = {"run_name": TRACE_NAME}
    if not settings.langfuse_enabled:
        return base
    try:
        return {
            **base,
            "callbacks": [_build_handler(settings)],
            "metadata": {"langfuse_tags": ["sangam", settings.model]},
        }
    except Exception:  # telemetry must never take the app down
        logger.warning(
            "Langfuse keys are set but tracing could not be enabled — continuing without it",
            exc_info=True,
        )
        return base


class SessionScopedAGUIAgent(LangGraphAGUIAgent):
    """AG-UI agent that tags each run with the conversation it belongs to.

    Subclasses the CopilotKit agent the app actually mounts (it extends
    `LangGraphAgent` and does not override `prepare_stream`), so CopilotKit's
    own behaviour is preserved.

    `prepare_stream` is the one hook that sees both the per-request
    `RunAgentInput` (which carries `thread_id`) and the `RunnableConfig` handed
    to the graph, so it is where a per-conversation id can be attached. Pinned
    to this library's signature on purpose — if an upgrade changes it, the
    override stops applying and traces lose their grouping, which the
    `test_tracing.py` unit tests catch.
    """

    async def prepare_stream(
        self,
        input: RunAgentInput,
        agent_state: dict[str, Any],
        config: RunnableConfig,
    ):
        config = {
            **config,
            "metadata": {
                **(config.get("metadata") or {}),
                "langfuse_session_id": input.thread_id,
                "langfuse_user_id": str(DEV_USER_ID),
                # Request context, per Langfuse's metadata guidance: lets a
                # trace be tied back to the AG-UI run that produced it.
                "agui_run_id": input.run_id,
            },
        }
        return await super().prepare_stream(
            input=input, agent_state=agent_state, config=config
        )


@contextmanager
def sql_span(name: str, sql: str, params: Any = None):
    """Record one SQL statement as a child of the span that is current.

    Langfuse's LangChain handler attaches the tool's span to the OpenTelemetry
    context for the duration of the tool body (`on_tool_start` attaches,
    `on_tool_end` detaches), so a span opened here nests under the tool call
    instead of starting a new trace.

    Typed `retriever` rather than a plain span: these statements are how the
    agent retrieves the context it answers from, which is what Langfuse's
    retrieval-oriented evaluators expect to find.

    Yields the observation, or None when tracing is off — callers must
    tolerate None.
    """
    try:
        from langfuse import get_client

        cm = get_client().start_as_current_observation(
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
    """`conn.execute(...).fetchall()`, with the statement recorded on the trace.

    Without this the trace shows a tool's arguments and its formatted output but
    not the query in between, which is the part you need when a tool returns
    the wrong rows.

    `prepare` is forwarded to psycopg. It matters for model-written SQL:
    prepare=True forces the extended query protocol, and the SERVER then refuses
    multiple commands in one statement ("cannot insert multiple commands into a
    prepared statement"). With the simple protocol, `SELECT 1; RESET ROLE`
    executes. Callers that need that guarantee must pass it explicitly rather
    than rely on the pool's prepare_threshold, which is a setting someone could
    change without knowing it was load-bearing.
    """
    with sql_span(name, sql, params) as span:
        kwargs = {} if prepare is None else {"prepare": prepare}
        rows = await (await conn.execute(sql, params, **kwargs)).fetchall()
        if span is not None:
            span.update(output={"row_count": len(rows)})
        return rows

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

import logging
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


def trace_config(settings: Settings) -> dict[str, Any]:
    """Config fragment attaching Langfuse to the agent graph.

    Returns the run name alone when tracing is off, so the graph is named
    consistently whether or not Langfuse is configured.
    """
    base: dict[str, Any] = {"run_name": TRACE_NAME}
    if not settings.langfuse_enabled:
        return base
    try:
        from langfuse.langchain import CallbackHandler

        return {
            **base,
            # update_trace lifts name/input/output/metadata from the root chain
            # onto the trace itself — without it the trace list shows nothing.
            "callbacks": [CallbackHandler(update_trace=True)],
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

    Yields the span, or None when tracing is off — callers must tolerate None.
    """
    try:
        from langfuse import get_client

        cm = get_client().start_as_current_span(
            name=name,
            input={"sql": dedent(sql).strip(), "params": params},
        )
    except Exception:  # never fail a query over telemetry
        logger.debug("SQL span could not be started", exc_info=True)
        yield None
        return

    with cm as span:
        yield span


async def traced_fetch(conn: Any, sql: str, params: Any = None, *, name: str) -> list[Any]:
    """`conn.execute(...).fetchall()`, with the statement recorded on the trace.

    Without this the trace shows a tool's arguments and its formatted output but
    not the query in between, which is the part you need when a tool returns
    the wrong rows.
    """
    with sql_span(name, sql, params) as span:
        rows = await (await conn.execute(sql, params)).fetchall()
        if span is not None:
            span.update(output={"row_count": len(rows)})
        return rows

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
    except Exception:  # noqa: BLE001 - telemetry must never take the app down
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

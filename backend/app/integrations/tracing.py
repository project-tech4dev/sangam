"""Langfuse tracing wiring."""

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

# Where row data begins in a tool result. Everything BEFORE these markers describes the query and is what
# you actually read a trace for; everything after is warehouse rows.
_GRID_HEADER = "columns: "          # db_query, from render_rows()
_PROFILE_HEADER = "as stored:"      # db_profile_column


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


def configure_langfuse(settings: Settings) -> bool:
    """Build the Langfuse client once, with masking and clipping attached."""
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
        # v3 shares resources per public key and the FIRST construction wins, so a client
        # built before this leaves masking silently off. Verified, not assumed.
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
    """Attach a score to the trace of the turn being handled."""
    try:
        from langfuse import get_client

        get_client().score_current_trace(name=name, value=value, comment=comment)
    except Exception:
        logger.debug("could not attach score %r", name, exc_info=True)



def _build_handler(settings: Settings):
    """The LangChain handler, bound to the client configure_langfuse() built."""
    from langfuse.langchain import CallbackHandler

    class _CancellationTolerantHandler(CallbackHandler):
        """Treats a cancelled turn as control flow, not an error."""

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
    """Config fragment attaching Langfuse to the agent graph."""
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
    """AG-UI agent that tags each run with the conversation it belongs to."""

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
    """Record one SQL statement as a child of the span that is current."""
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
    """`conn.execute(...).fetchall()`, with the statement recorded on the trace."""
    with sql_span(name, sql, params) as span:
        kwargs = {} if prepare is None else {"prepare": prepare}
        rows = await (await conn.execute(sql, params, **kwargs)).fetchall()
        if span is not None:
            span.update(output={"row_count": len(rows)})
        return rows

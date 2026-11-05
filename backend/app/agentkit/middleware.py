"""Middleware every deep agent shares: tool errors, old-result clearing, model fallback and the summarizer."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import Any, NotRequired

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.summarization import SummarizationMiddleware, compute_summarization_defaults
from langchain.agents.middleware import (
    AgentState,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelFallbackMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.language_models import BaseChatModel

from app.agentkit.models import resolve_model

logger = logging.getLogger(__name__)

# Bulky old result grids are dead weight once the model has read them, but the
# most recent few are what a follow-up question refers back to.
TOOL_RESULT_CLEAR_TRIGGER_TOKENS = 60_000
TOOL_RESULTS_KEPT = 5
# Clearing grows in steps of this size, so the cleared set (and the cached prefix) moves once per step.
TOOL_RESULTS_CLEAR_STEP = 20_000
# compare_fit is bounded and is what the write-up reads; clearing it made the model call it again.
NEVER_CLEARED = ("compare_fit",)


@dataclass(slots=True)
class SteppedClearToolUsesEdit(ClearToolUsesEdit):
    """Past the trigger, reclaim whole steps: a fixed clear_at_least clears the same few results forever."""

    step: int = TOOL_RESULTS_CLEAR_STEP

    def apply(self, messages, *, count_tokens) -> None:
        over = count_tokens(messages) - self.trigger
        if over <= 0:
            return
        reclaim = math.ceil(over / self.step) * self.step
        ClearToolUsesEdit.apply(replace(self, clear_at_least=reclaim), messages, count_tokens=count_tokens)


def _tool_failed(exc: Exception, request) -> str:
    name = request.tool_call.get("name") or "tool"
    logger.warning("%s raised past its own try/except", name, exc_info=exc)
    # The type only: a raw message can carry SQL, paths or keys.
    return f"{name} failed: {type(exc).__name__}. Try another way, or tell the person what could not be done."


def tool_errors() -> ToolErrorMiddleware:
    """Backstop for the tools' try/except convention: a tool that raises answers the model instead of ending the run."""
    return ToolErrorMiddleware(_tool_failed)


def clear_old_tool_results() -> ContextEditingMiddleware:
    """Drop bulky old tool output from the request once context grows large."""
    return ContextEditingMiddleware(
        edits=[
            SteppedClearToolUsesEdit(
                trigger=TOOL_RESULT_CLEAR_TRIGGER_TOKENS,
                keep=TOOL_RESULTS_KEPT,
                exclude_tools=NEVER_CLEARED,
            )
        ]
    )


# Haiku's window is 200k; the summary prompt and its answer need the rest.
SUMMARY_INPUT_TOKENS = 150_000


def fallback(primary: str, *candidates: str) -> list[ModelFallbackMiddleware]:
    """The first candidate that differs from `primary`, tried when its call fails; none if all match."""
    spare = next((c for c in candidates if c and c != primary), None)
    return [ModelFallbackMiddleware(resolve_model(spare))] if spare else []


class AgUiState(AgentState):
    pass


# The key ag-ui-langgraph writes the client's context to; LangGraph drops a key no schema declares.
AgUiState.__annotations__["ag-ui"] = NotRequired[dict[str, Any]]


def cheap_summarizer(own: BaseChatModel, summarizer: BaseChatModel, backend: BackendProtocol) -> SummarizationMiddleware:
    """Replaces the agent's own summarizer by name: same thresholds as `own` gets today, written by `summarizer`."""
    defaults = compute_summarization_defaults(own)
    return SummarizationMiddleware(
        model=summarizer,
        backend=backend,
        trigger=defaults["trigger"],
        keep=defaults["keep"],
        truncate_args_settings=defaults["truncate_args_settings"],
        trim_tokens_to_summarize=SUMMARY_INPUT_TOKENS,
    )

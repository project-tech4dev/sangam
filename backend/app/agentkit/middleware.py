"""Middleware every deep agent shares: tool errors, old-result clearing, model fallback and the summarizer."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import Any, NotRequired

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.summarization import DEEPAGENTS_DEFAULT_SUMMARY_PROMPT, SummarizationMiddleware
from langchain.agents.middleware import (
    AgentState,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelFallbackMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

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


ANSWERED_PLACEHOLDER = (
    "[Cleared: this result's question was answered above, and the rows the answer used are cited in it. "
    "Run the query again if you need more of them.]"
)


@dataclass(slots=True)
class ClearAnsweredTurnsEdit:
    """Clear tool results from questions already answered; the boundary is fixed for a turn, so its calls share a cache."""

    exclude_tools: tuple[str, ...] = NEVER_CLEARED
    placeholder: str = ANSWERED_PLACEHOLDER

    def apply(self, messages: list[AnyMessage], *, count_tokens) -> None:
        last_question = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), 0)
        calls = {c["id"]: c["name"] for m in messages[:last_question] if isinstance(m, AIMessage) for c in m.tool_calls}
        for idx, message in enumerate(messages[:last_question]):
            if not isinstance(message, ToolMessage) or message.response_metadata.get("context_editing", {}).get("cleared"):
                continue
            name = message.name or calls.get(message.tool_call_id)
            if name is None or name in self.exclude_tools:
                continue
            messages[idx] = message.model_copy(update={
                "artifact": None,
                "content": self.placeholder,
                "response_metadata": {**message.response_metadata,
                                      "context_editing": {"cleared": True, "strategy": "answered_turn"}},
            })


def _tool_failed(exc: Exception, request) -> str:
    name = request.tool_call.get("name") or "tool"
    logger.warning("%s raised past its own try/except", name, exc_info=exc)
    # The type only: a raw message can carry SQL, paths or keys.
    return f"{name} failed: {type(exc).__name__}. Try another way, or tell the person what could not be done."


def tool_errors() -> ToolErrorMiddleware:
    """Backstop for the tools' try/except convention: a tool that raises answers the model instead of ending the run."""
    return ToolErrorMiddleware(_tool_failed)


def clear_old_tool_results(*, answered_turns: bool = False, trigger: int = TOOL_RESULT_CLEAR_TRIGGER_TOKENS,
                           keep_tools: tuple[str, ...] = ()) -> ContextEditingMiddleware:
    """Drop bulky old tool output from the request once context grows large; `answered_turns` also clears every
    result from a question already answered (Ask, where each question stands on its own answer)."""
    return ContextEditingMiddleware(
        edits=[
            *([ClearAnsweredTurnsEdit()] if answered_turns else []),
            SteppedClearToolUsesEdit(
                trigger=trigger,
                keep=TOOL_RESULTS_KEPT,
                exclude_tools=(*NEVER_CLEARED, *keep_tools),
            )
        ]
    )


# Haiku's window is 200k; the summary prompt and its answer need the rest.
SUMMARY_INPUT_TOKENS = 150_000
# Fixed sizes, not a share of the window: a 1M profile put the trigger at 850k, and a model with no profile kept 6 messages.
SUMMARY_TRIGGER = ("tokens", 170_000)
SUMMARY_KEEP = ("tokens", 20_000)
# A fact must still name its page after a summary; the default prompt kept "thecsrjournal.in" and lost the page.
SOURCES_SECTION = """## SOURCES

List every page or document read, by its full URL (never just the site), with the facts and exact quotes taken from \
each and the page number for a PDF. Copy every URL character for character. Write "None" if nothing was read.

</instructions>"""
SUMMARY_PROMPT = DEEPAGENTS_DEFAULT_SUMMARY_PROMPT.replace("</instructions>", SOURCES_SECTION, 1)
if "## SOURCES" not in SUMMARY_PROMPT:
    raise RuntimeError("deepagents' summary prompt has no </instructions> tag; the SOURCES section has nowhere to go")


def fallback(primary: str, *candidates: str) -> list[ModelFallbackMiddleware]:
    """The first candidate that differs from `primary`, tried when its call fails; none if all match."""
    spare = next((c for c in candidates if c and c != primary), None)
    return [ModelFallbackMiddleware(resolve_model(spare))] if spare else []


class AgUiState(AgentState):
    pass


# The key ag-ui-langgraph writes the client's context to; LangGraph drops a key no schema declares.
AgUiState.__annotations__["ag-ui"] = NotRequired[dict[str, Any]]


def cheap_summarizer(summarizer: BaseChatModel, backend: BackendProtocol) -> SummarizationMiddleware:
    """Replaces the agent's own summarizer by name: the same token thresholds for every model, written by `summarizer`."""
    return SummarizationMiddleware(
        model=summarizer,
        backend=backend,
        trigger=SUMMARY_TRIGGER,
        keep=SUMMARY_KEEP,
        truncate_args_settings={"trigger": SUMMARY_TRIGGER, "keep": SUMMARY_KEEP},
        trim_tokens_to_summarize=SUMMARY_INPUT_TOKENS,
        summary_prompt=SUMMARY_PROMPT,
    )

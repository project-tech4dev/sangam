"""Import's LangChain middleware: fallbacks, the researcher's budgets, escalation, rubric and summarizer."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from importlib.resources import files
from typing import Any

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware._utils import append_to_system_message
from deepagents.middleware.rubric import RubricEvaluation, RubricMiddleware
from deepagents.middleware.summarization import SummarizationMiddleware, compute_summarization_defaults
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRequest,
)
from langchain.agents.middleware.types import hook_config
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from app.agent.models import resolve_model
from app.ingest.caller import caller_note, scope

logger = logging.getLogger(__name__)

READING_TOOLS = frozenset({"read_page", "fetch_document", "read_document_pages"})
SAVE_TOOL = "save_research"
# The phrase the researcher copies into stopped_reason; the Working board matches it.
READING_LIMIT = "reading limit"
READING_LIMIT_MESSAGE = (
    f"Refused: the {READING_LIMIT} for this organisation is reached. Read nothing more. Call save_research "
    f"now with what you have, and set stopped_reason to 'Stopped at the {READING_LIMIT}' plus what was left unread."
)
# Haiku's window is 200k; the summary prompt and its answer need the rest.
SUMMARY_INPUT_TOKENS = 150_000

RUBRIC = (files("app.ingest") / "prompts" / "research_rubric.md").read_text(encoding="utf-8")


def fallback(primary: str, *candidates: str) -> list[ModelFallbackMiddleware]:
    """The first candidate that differs from `primary`, tried when its call fails; none if all match."""
    spare = next((c for c in candidates if c and c != primary), None)
    return [ModelFallbackMiddleware(resolve_model(spare))] if spare else []


class ReadingLimit(AgentMiddleware):
    """Refuses page reads past `limit` in one run, so a researcher saves what it has instead of reading on."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def _refusal(self, request: Any) -> ToolMessage | None:
        call = request.tool_call
        if call["name"] not in READING_TOOLS:
            return None
        # Counted from the run's own messages, so parallel reads in one turn are numbered in order.
        n = 0
        for message in _messages(request.state):
            for tc in getattr(message, "tool_calls", None) or []:
                if tc["name"] in READING_TOOLS:
                    n += 1
                    if tc["id"] == call["id"]:
                        return _refused(call) if n > self.limit else None
        return None

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return self._refusal(request) or await handler(request)


def _refused(call: dict) -> ToolMessage:
    return ToolMessage(content=READING_LIMIT_MESSAGE, tool_call_id=call["id"], name=call["name"])


def _messages(state: Any) -> list[AnyMessage]:
    return (state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)) or []


def save_failed(messages: list[AnyMessage]) -> bool:
    """A save_research call came back as an argument error: the payload, not the database, was wrong."""
    return any(
        isinstance(m, ToolMessage)
        and m.name == SAVE_TOOL
        and (m.status == "error" or str(m.content).startswith("Error invoking tool"))
        for m in messages
    )


class EscalateAfterFailedSave(AgentMiddleware):
    """After a failed save, the rest of the run is on the strong model: one invalid payload loses the research."""

    def __init__(self, strong: BaseChatModel) -> None:
        super().__init__()
        self.strong = strong

    def _route(self, request: ModelRequest) -> ModelRequest:
        return request.override(model=self.strong) if save_failed(request.messages) else request

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Any]) -> Any:
        return handler(self._route(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]) -> Any:
        return await handler(self._route(request))


class CallerNote(AgentMiddleware):
    """Tells the supervisor who this run works for, so it offers only what they may do. The tools still check."""

    def _with_note(self, request: ModelRequest) -> ModelRequest:
        return request.override(system_message=append_to_system_message(request.system_message, caller_note(scope())))

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Any]) -> Any:
        return handler(self._with_note(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]) -> Any:
        return await handler(self._with_note(request))


class ResearchRubric(RubricMiddleware):
    """RubricMiddleware with a fixed rubric, so the task tool needn't pass one.

    Supplied to the hooks, never written to state: a public `rubric` key would flow back into the parent.
    """

    def _with_rubric(self, state: Any) -> dict:
        return {**state, "rubric": RUBRIC}

    def before_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return super().before_agent(self._with_rubric(state), runtime)

    async def abefore_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return await super().abefore_agent(self._with_rubric(state), runtime)

    # Redeclared: an override without it loses the edge back to the model, and a revision never runs.
    @hook_config(can_jump_to=["model"])
    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return super().after_agent(self._with_rubric(state), runtime)

    @hook_config(can_jump_to=["model"])
    async def aafter_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return await super().aafter_agent(self._with_rubric(state), runtime)


def digest_saves(messages: list[AnyMessage]) -> list[AnyMessage]:
    """The grader sees a save_research call as its counts and concepts: the full payload is cut at 4,000 chars."""
    out: list[AnyMessage] = []
    for m in messages:
        calls = getattr(m, "tool_calls", None) or []
        if isinstance(m, AIMessage) and any(c["name"] == SAVE_TOOL for c in calls):
            text = m.text if isinstance(m.text, str) else ""
            calls = [{**c, "args": _digest(c["args"])} if c["name"] == SAVE_TOOL else c for c in calls]
            m = AIMessage(content=text, tool_calls=calls, id=m.id)
        out.append(m)
    return out


def _digest(args: dict) -> dict:
    research = args.get("findings") or {}
    findings = research.get("findings") or []
    return {
        "status": research.get("status"),
        "stopped_reason": research.get("stopped_reason"),
        "goals": research.get("goals") or [],
        "finding_count": len(findings),
        "concepts_found": sorted({f.get("concept") for f in findings if f.get("concept")}),
        "gaps": [
            {k: g.get(k) for k in ("concept", "fiscal_year", "reason", "detail")} for g in research.get("gaps") or []
        ],
    }


def _log_evaluation(evaluation: RubricEvaluation) -> None:
    logger.info("research rubric: %s (iteration %s)", evaluation["result"], evaluation["iteration"])


def research_rubric(grader: BaseChatModel) -> ResearchRubric:
    """Grades the researcher's save and summary before it reports; at most one revision."""
    return ResearchRubric(
        model=grader,
        max_iterations=2,
        prepare_messages_for_grader=digest_saves,
        on_evaluation=_log_evaluation,
    )


def call_limit(limit: int) -> ModelCallLimitMiddleware:
    """A hard stop on a looping run. Ending leaves no structured summary; the task tool falls back to its text."""
    return ModelCallLimitMiddleware(run_limit=limit, exit_behavior="end")


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

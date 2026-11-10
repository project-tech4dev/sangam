"""Import's LangChain middleware: fallbacks, the researcher's budgets, escalation, rubric and summarizer."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from importlib.resources import files
from typing import Any, NotRequired

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.rubric import GraderResponse, RubricEvaluation, RubricMiddleware
from deepagents.middleware.summarization import SummarizationMiddleware, compute_summarization_defaults
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRequest,
    ModelResponse,
    TodoListMiddleware,
)
from langchain.agents.middleware.types import hook_config
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from app.agent.models import resolve_model
from app.ingest import run_sources
from app.ingest.caller import caller_note, scope
from app.ingest.research_records import FINDING_MODELS, EntityResearch, VaultResearch

logger = logging.getLogger(__name__)

READING_TOOLS = frozenset({"read_page", "fetch_document", "read_document_pages"})
SAVE_TOOL = "save_research"
# The phrase the researcher copies into stopped_reason; the Working board matches it.
READING_LIMIT = "reading limit"
READING_LIMIT_MESSAGE = (
    f"Refused: the {READING_LIMIT} for this organisation is reached. Read nothing more. Call save_research "
    f"now with what you have, and set stopped_reason to 'Stopped at the {READING_LIMIT}' plus what was left unread."
)
# What ModelCallLimitMiddleware's exit_behavior="end" says as it stops a run.
CALL_LIMIT_PREFIX = "Model call limits exceeded"
# The library's own write_todos prompt and description run ~2k tokens on every supervisor call.
PLAN_PROMPT = (
    "## `write_todos`\n\nThe run's plan, kept in state so it survives a summary. Write it once, after the dossier "
    "and before the first launch: one todo per organisation, prefixed with its wave (\"Wave 1: Axis Bank "
    "Foundation\"), then \"Report\". Mark a wave's todos completed when its researchers return, and add any "
    "organisation the person adds mid-run. Never call it in the same message as `task`. Skip it when the run "
    "researches nothing. The report is a message after the last `write_todos`."
)
PLAN_TOOL = ("Write or replace the run's plan: every todo, each pending, in_progress or completed. "
             "See `write_todos` in your instructions.")
# Haiku's window is 200k; the summary prompt and its answer need the rest.
SUMMARY_INPUT_TOKENS = 150_000

RUBRIC = (files("app.ingest") / "prompts" / "research_rubric.md").read_text(encoding="utf-8")


def append_to_system_message(system: SystemMessage | None, text: str) -> SystemMessage:
    """A text block after the system message's own; ours, since deepagents keeps its copy private."""
    blocks: list[Any] = list(system.content_blocks) if system else []
    return SystemMessage(content_blocks=[*blocks, {"type": "text", "text": f"\n\n{text}" if blocks else text}])


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


SAVE_SCHEMAS: dict[str, type[BaseModel]] = {SAVE_TOOL: EntityResearch, "save_vault_findings": VaultResearch}
# ToolNode echoes the whole payload before the error, so a big save's reason was evicted and cut off.
REFUSAL_LINES = 25
_LABELS = ("partner_name", "program_name", "project_name", "title", "name", "id_type", "state", "fiscal_year")


def _problem(error: dict[str, Any], payload: dict[str, Any], schema: type[BaseModel]) -> str:
    loc, msg = error["loc"], error["msg"].removeprefix("Value error, ")
    if len(loc) >= 2 and loc[0] == "findings" and isinstance(loc[1], int):
        finding = (payload.get("findings") or [None] * (loc[1] + 1))[loc[1]]
        finding = finding if isinstance(finding, dict) else {}
        concept = finding.get("concept", "?")
        label = next((str(finding[k])[:60] for k in _LABELS if finding.get(k)), "")
        where = f"finding {loc[1]} ({concept}{f' {label!r}' if label else ''})"
        field = ".".join(str(p) for p in loc[3:])
        model = FINDING_MODELS.get(concept)
        if error["type"] == "extra_forbidden" and model:
            return (f"{where}: `{field}` is not a field of {concept}. Allowed: {', '.join(model.model_fields)}. "
                    "Put the remark in evidence or drop it.")
        return f"{where}{f' {field}' if field else ''}: {msg}"
    field = ".".join(str(p) for p in loc)
    if error["type"] == "extra_forbidden":
        if field == "replace":
            return "top level: `replace` is an argument beside `findings`, never inside it"
        return f"top level: `{field}` is not a field. Allowed: {', '.join(schema.model_fields)}"
    return f"top level{f' {field}' if field else ''}: {msg}"


def parse_payload(text: str) -> dict[str, Any] | None:
    """A payload sent as a JSON string. Only surplus closing brackets after the object are forgiven."""
    text = text.strip()
    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    if text[end:].strip(" \t\r\n}]"):
        return None
    return value if isinstance(value, dict) else None


def _not_json(name: str, text: str) -> str:
    try:
        json.loads(text)
        reason = "it parses, but not as an object"
    except ValueError as exc:
        pos = getattr(exc, "pos", 0)
        reason = f"{getattr(exc, 'msg', exc)} at character {pos}, near {text[max(0, pos - 60):pos + 20]!r}"
    return (f"Error invoking tool '{name}': refused, nothing saved. `findings` arrived as a string that is "
            f"not valid JSON ({reason}). Send `findings` as an object, not a string, and call {name} again "
            "with the whole payload.")


def refusal_text(name: str, payload: Any) -> str | None:
    """One line per schema problem in a refused save, or None when the payload validates."""
    if isinstance(payload, str) and parse_payload(payload) is None:
        return _not_json(name, payload)
    schema = SAVE_SCHEMAS[name]
    try:
        schema.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors()
    else:
        return None
    data = payload if isinstance(payload, dict) else {}
    lines = [f"- {_problem(e, data, schema)}" for e in errors[:REFUSAL_LINES]]
    if len(errors) > REFUSAL_LINES:
        lines.append(f"- and {len(errors) - REFUSAL_LINES} more of the same kinds")
    return (f"Error invoking tool '{name}': refused, nothing saved. Fix these {len(errors)} and call {name} "
            "again with the whole payload:\n" + "\n".join(lines))


class SaveRefusal(AgentMiddleware):
    """A refused save comes back as the list of fixes, not the payload echoed in front of them."""

    def _parsed(self, request: Any) -> Any:
        # Models sometimes send the payload as a JSON string; parsing it costs nothing and loses nothing.
        call = request.tool_call
        findings = (call.get("args") or {}).get("findings")
        if call.get("name") not in SAVE_SCHEMAS or not isinstance(findings, str):
            return request
        payload = parse_payload(findings)
        if payload is None:
            return request
        return request.override(tool_call={**call, "args": {**call["args"], "findings": payload}})

    def _short(self, request: Any, result: Any) -> Any:
        name = request.tool_call.get("name")
        if (name not in SAVE_SCHEMAS or not isinstance(result, ToolMessage) or result.status != "error"
                or not str(result.content).startswith("Error invoking tool")):
            return result
        try:
            text = refusal_text(name, (request.tool_call.get("args") or {}).get("findings"))
        except Exception:  # noqa: BLE001 - a failed rewrite keeps the original error
            text = None
        return result.model_copy(update={"content": text}) if text else result

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        request = self._parsed(request)
        return self._short(request, handler(request))

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        request = self._parsed(request)
        return self._short(request, await handler(request))


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


class DropFilesOnExit(AgentMiddleware):
    """Deletes every file in a subagent's state as it ends. Its files flow back to the parent and on into
    the next subagent, so anything the vault-reader offloaded (a summary, a long read) would reach a researcher."""

    def _drop(self, state: Any) -> dict[str, Any] | None:
        files = (state.get("files") if isinstance(state, dict) else getattr(state, "files", None)) or {}
        return {"files": dict.fromkeys(files)} if files else None

    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self._drop(state)

    async def aafter_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self._drop(state)


class CallerNote(AgentMiddleware):
    """Tells the supervisor who this run works for, so it offers only what they may do. The tools still check."""

    def _with_note(self, request: ModelRequest) -> ModelRequest:
        return request.override(system_message=append_to_system_message(request.system_message, caller_note(scope())))

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Any]) -> Any:
        return handler(self._with_note(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]) -> Any:
        return await handler(self._with_note(request))


# The Import screen sends this context with the first message; the frontend uses the same words.
TICKED_SOURCES = "Sources the person ticked for this Import run"


class _AgUiState(AgentState):
    pass


# The key ag-ui-langgraph writes the client's context to; LangGraph drops a key no schema declares.
_AgUiState.__annotations__["ag-ui"] = NotRequired[dict[str, Any]]


def _field(item: Any, key: str) -> Any:
    # ag-ui-langgraph stores its pydantic Context objects, not dicts.
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


def _ticked_value(state: Any) -> Any:
    items = _field((state or {}).get("ag-ui") or {}, "context") or []
    return next((_field(c, "value") for c in items if _field(c, "description") == TICKED_SOURCES), None)


def ticked_sources(state: Any) -> dict[str, Any] | None:
    """choose_sources' arguments as the person ticked them before sending, or None if nothing was ticked."""
    value = _ticked_value(state)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict):
        return None
    vault_org = value.get("vault_org")
    picked = {
        "web": value.get("web") is True,
        "library": value.get("library") is True,
        "vault_org": vault_org if isinstance(vault_org, int) else None,
        "vault_docs": [d for d in value.get("vault_docs") or [] if isinstance(d, int)],
        "staff_paths": [p for p in value.get("staff_paths") or [] if isinstance(p, str)],
    }
    return picked if picked["web"] or picked["library"] or picked["vault_docs"] or picked["staff_paths"] else None


def ask_for_sources(request: Any) -> bool:
    """choose_sources pauses for the card only when nothing was ticked: a tick is already the person's answer."""
    return ticked_sources(request.state) is None


def ticked_note(state: Any) -> str | None:
    picked = ticked_sources(state)
    if not picked:
        return None
    return (f"The person ticked these sources before sending: {json.dumps(picked)}. Call choose_sources with "
            "exactly these and say nothing about choosing or confirming sources.")


def _ai_messages(response: Any) -> list[AIMessage]:
    inner = getattr(response, "model_response", response)
    messages = inner.result if isinstance(inner, ModelResponse) else [inner]
    return [m for m in messages if isinstance(m, AIMessage)]


class TickedSources(AgentMiddleware):
    """The person's ticks answer choose_sources: told to the model, and written into its call whatever it passed."""

    state_schema = _AgUiState

    def _with_note(self, request: ModelRequest) -> ModelRequest:
        note = ticked_note(request.state)
        return request.override(system_message=append_to_system_message(request.system_message, note)) if note \
            else request

    def _with_ticks(self, request: ModelRequest, response: Any) -> Any:
        picked = ticked_sources(request.state)
        if picked:
            for message in _ai_messages(response):
                for call in message.tool_calls:
                    if call["name"] == run_sources.CHOOSE:
                        call["args"] = dict(picked)
        return response

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Any]) -> Any:
        return self._with_ticks(request, handler(self._with_note(request)))

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]) -> Any:
        return self._with_ticks(request, await handler(self._with_note(request)))


def _not_chosen(call: dict[str, Any], text: str) -> ToolMessage:
    return ToolMessage(content=text, tool_call_id=call.get("id") or "", name=call.get("name"), status="error")


class ChosenSources(AgentMiddleware):
    """The supervisor's half: no subagent before the person answers choose_sources, and each one launched
    carries that answer, so the subagent's own RunSources can enforce it."""

    def _sources(self, request: Any) -> run_sources.Sources | ToolMessage | None:
        if request.tool_call.get("name") != "task":
            return None
        try:
            chosen = run_sources.chosen(_messages(request.state))
        except Exception:  # noqa: BLE001 - unreadable state fails closed
            chosen = None
        return chosen or _not_chosen(request.tool_call, (
            "REFUSED: call choose_sources first, on its own, and wait for the person's answer before "
            "launching any subagent."))

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        sources = self._sources(request)
        if isinstance(sources, ToolMessage):
            return sources
        token = run_sources.CURRENT.set(sources) if sources else None
        try:
            return handler(request)
        finally:
            if token:
                run_sources.CURRENT.reset(token)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        sources = self._sources(request)
        if isinstance(sources, ToolMessage):
            return sources
        token = run_sources.CURRENT.set(sources) if sources else None
        try:
            return await handler(request)
        finally:
            if token:
                run_sources.CURRENT.reset(token)


class RunSources(AgentMiddleware):
    """A subagent's half: refuses any read outside what the person chose for this run."""

    def _refusal(self, request: Any) -> ToolMessage | None:
        call = request.tool_call
        why = run_sources.refusal(run_sources.CURRENT.get(), call.get("name") or "", call.get("args") or {})
        return _not_chosen(call, why) if why else None

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return self._refusal(request) or await handler(request)


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
        return None if stopped_by_call_limit(state) else super().after_agent(self._with_rubric(state), runtime)

    @hook_config(can_jump_to=["model"])
    async def aafter_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if stopped_by_call_limit(state):
            return None
        return await super().aafter_agent(self._with_rubric(state), runtime)

    def _handle_grader_exception(self, runtime: Any, state: Any, grading_run_id: str, iteration: int,
                                 exc: Exception) -> dict[str, Any]:
        # Haiku sometimes says needs_revision while passing every criterion; with every criterion passed, it is satisfied.
        if (graded := all_passed(exc)) is not None:
            return self._finalize_evaluation(graded, state, runtime, grading_run_id, iteration)
        return super()._handle_grader_exception(runtime, state, grading_run_id, iteration, exc)


def all_passed(exc: BaseException) -> GraderResponse | None:
    """The grader's verdict as 'satisfied' when its only fault was 'needs_revision' with no criterion failing."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValidationError):
            for error in current.errors():
                verdict = error.get("input")
                if "every criterion has passed=True" in error.get("msg", "") and isinstance(verdict, dict):
                    try:
                        return GraderResponse.model_validate({**verdict, "result": "satisfied"})
                    except ValidationError:
                        return None
        current = current.__cause__ or current.__context__
    return None


def stopped_by_call_limit(state: Any) -> bool:
    """call_limit ended the run: a revision would only be ended again, so there is nothing to grade."""
    last = next((m for m in reversed(_messages(state)) if isinstance(m, AIMessage)), None)
    return bool(last) and isinstance(last.content, str) and last.content.startswith(CALL_LIMIT_PREFIX)


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
    if isinstance(research, str):
        research = parse_payload(research) or {}
    findings = research.get("findings") or []
    return {
        "status": research.get("status"),
        "stopped_reason": research.get("stopped_reason"),
        "goals": research.get("goals") or [],
        "finding_count": len(findings),
        "concepts_found": sorted({f.get("concept") for f in findings if f.get("concept")}),
        "programs_untagged": [f.get("name") for f in findings
                              if f.get("concept") == "program" and not f.get("themes")],
        "gaps": [
            {k: g.get(k) for k in ("concept", "fiscal_year", "field", "reason", "detail")}
            for g in research.get("gaps") or []
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


def run_plan() -> TodoListMiddleware:
    return TodoListMiddleware(system_prompt=PLAN_PROMPT, tool_description=PLAN_TOOL)

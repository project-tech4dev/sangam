"""Import's LangChain middleware: the researcher's budgets, escalation, sources and the run's summary counts."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    TodoListMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from app.agentkit.middleware import AgUiState
from app.db.checkpointer import thread_bytes
from app.db.pool import get_pool
from app.ingest.caller import caller_note, scope
from app.ingest.catalog.save import write_preview
from app.ingest.reading import run_sources, snapshots
from app.ingest.research import draft
from app.ingest.research.finding_types import FINDING_MODELS
from app.ingest.research.findings import VaultResearch
from app.integrations.tracing import score_answer

logger = logging.getLogger(__name__)

READING_TOOLS = frozenset({"read_page", "fetch_document", "read_document_pages"})


def _reads(call: dict) -> bool:
    """A find inside a document only lists page numbers, so it spends none of the reading limit."""
    finding = call["name"] == "read_document_pages" and (call.get("args") or {}).get("find")
    return call["name"] in READING_TOOLS and not finding

CHECKPOINT_SIZE_WAIT_S = 2
# The phrase the researcher copies into stopped_reason; the Working board matches it.
READING_LIMIT = "reading limit"
READING_LIMIT_MESSAGE = (
    f"Refused: the {READING_LIMIT} for this organisation is reached. Read nothing more. Record what you have, then "
    f"call save_research with stopped_reason 'Stopped at the {READING_LIMIT}' plus what was left unread."
)
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

def append_to_system_message(system: SystemMessage | None, text: str) -> SystemMessage:
    """A text block after the system message's own; ours, since deepagents keeps its copy private."""
    blocks: list[Any] = list(system.content_blocks) if system else []
    return SystemMessage(content_blocks=[*blocks, {"type": "text", "text": f"\n\n{text}" if blocks else text}])


class ReadingLimit(AgentMiddleware):
    """Refuses page reads past `limit` in one run, so a researcher saves what it has instead of reading on."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def _refusal(self, request: Any) -> ToolMessage | None:
        call = request.tool_call
        if not _reads(call):
            return None
        # Counted from the run's own messages, so parallel reads in one turn are numbered in order.
        n = 0
        for message in _messages(request.state):
            for tc in getattr(message, "tool_calls", None) or []:
                if _reads(tc):
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


SAVE_SCHEMAS: dict[str, type[BaseModel]] = {"save_vault_findings": VaultResearch}
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
        return f"top level: `{field}` is not a field. Allowed: {', '.join(schema.model_fields)}"
    return f"top level{f' {field}' if field else ''}: {msg}"


def parse_payload(text: str) -> dict[str, Any] | None:
    """A payload sent as a JSON string, read as draft.parse_json forgives it; None unless it is an object."""
    value = draft.parse_json(text)
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


# Two saves refused for what they hold, not their shape, and the rest of the run is on the strong model.
ESCALATE_AFTER = 2


class EscalateAfterFailedSave(AgentMiddleware):
    """After ESCALATE_AFTER content refusals the run moves to the strong model; a format slip never escalates."""

    def __init__(self, strong: BaseChatModel) -> None:
        super().__init__()
        self.strong = strong

    def _route(self, request: ModelRequest) -> ModelRequest:
        current = draft.CURRENT.get()
        stuck = current is not None and current.refusals >= ESCALATE_AFTER
        return request.override(model=self.strong) if stuck else request

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Any]) -> Any:
        return handler(self._route(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]) -> Any:
        return await handler(self._route(request))


class DropFilesOnExit(AgentMiddleware):
    """Deletes every file in a subagent's state as it ends. Its files merge into Scout's saved state and on into
    the next subagent: an evicted page saved at every later step, or private vault text reaching a researcher."""

    def _drop(self, state: Any) -> dict[str, Any] | None:
        files = (state.get("files") if isinstance(state, dict) else getattr(state, "files", None)) or {}
        return {"files": dict.fromkeys(files)} if files else None

    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self._drop(state)

    async def aafter_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self._drop(state)


class CheckpointSize(AgentMiddleware):
    """Scores the thread's running checkpoint MB as a turn finishes; a turn paused on an approval counts in the next."""

    async def aafter_agent(self, state: Any, runtime: Any) -> None:
        try:
            thread_id = get_config()["configurable"]["thread_id"]
            # A dashboard number never holds up a turn behind a busy pool.
            async with get_pool().connection(timeout=CHECKPOINT_SIZE_WAIT_S) as conn:
                size = await thread_bytes(conn, thread_id)
        except Exception:
            logger.debug("could not measure checkpoint size", exc_info=True)
            return
        score_answer("checkpoint_mb", round(size / 1_000_000, 2))


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

    state_schema = AgUiState

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


def _open_run(stack: ExitStack) -> draft.Draft:
    """Each launched subagent gets its own snapshot list and findings draft."""
    stack.enter_context(snapshots.collecting())
    return stack.enter_context(draft.drafting())


def with_saved_counts(result: Any, current: draft.Draft | None) -> Any:
    """The researcher's summary with its counts taken from what was saved, not from what the model wrote."""
    if current is None or current.saved is None or not isinstance(result, Command):
        return result
    update = result.update if isinstance(result.update, dict) else {}
    messages = list(update.get("messages") or [])
    if not messages or not isinstance(messages[-1], ToolMessage):
        return result
    try:
        summary = json.loads(messages[-1].content)
    except (TypeError, ValueError):
        summary = None
    if not isinstance(summary, dict) or "fact_count" not in summary:
        return result
    saved = {k: v for k, v in current.saved.items() if k != "status"}
    messages[-1] = messages[-1].model_copy(update={"content": json.dumps({**summary, **saved, "saved": True})})
    return Command(graph=result.graph, update={**update, "messages": messages}, resume=result.resume, goto=result.goto)


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
            with ExitStack() as stack:
                current = _open_run(stack) if sources else None
                return with_saved_counts(handler(request), current)
        finally:
            if token:
                run_sources.CURRENT.reset(token)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        sources = self._sources(request)
        if isinstance(sources, ToolMessage):
            return sources
        token = run_sources.CURRENT.set(sources) if sources else None
        try:
            with ExitStack() as stack:
                current = _open_run(stack) if sources else None
                return with_saved_counts(await handler(request), current)
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


def call_limit(limit: int) -> ModelCallLimitMiddleware:
    """A hard stop on a looping run. Ending leaves no structured summary; the task tool falls back to its text."""
    return ModelCallLimitMiddleware(run_limit=limit, exit_behavior="end")


def run_plan() -> TodoListMiddleware:
    return TodoListMiddleware(system_prompt=PLAN_PROMPT, tool_description=PLAN_TOOL)


# The researcher reads untrusted pages and the staff workbooks; once it has seen a staff row, no
# outbound tool runs, so an injected instruction cannot carry a row out in a URL or query.
STAFF_TOOL = "read_source_rows"
# An allowlist, so an outbound tool added to the researcher later is closed by default.
OPEN_AFTER_STAFF = frozenset({STAFF_TOOL, "record_findings", "save_research", "read_document_pages", "research_goals",
                              "funder_dossier", "read_file"})
STAFF_LOCK_REPLY = "web tools are closed for this run: staff rows have been read. Save what you have."


def staff_rows_requested(messages: list[BaseMessage]) -> bool:
    """True once this run has asked for a staff read, including in the current turn."""
    for m in messages:
        if isinstance(m, ToolMessage) and m.name == STAFF_TOOL:
            return True
        if isinstance(m, AIMessage) and any(c.get("name") == STAFF_TOOL for c in m.tool_calls or []):
            return True
    return False


class StaffLastLock(AgentMiddleware):
    """Refuses every tool but OPEN_AFTER_STAFF for the rest of a run once read_source_rows has been called."""

    def _refusal(self, request) -> ToolMessage | None:
        call = request.tool_call
        if call.get("name") in OPEN_AFTER_STAFF:
            return None
        try:
            state = request.state
            messages = state["messages"] if isinstance(state, dict) else state.messages
            closed = staff_rows_requested(messages)
        except Exception:  # noqa: BLE001 - unreadable state fails closed
            closed = True
        if not closed:
            return None
        return ToolMessage(content=STAFF_LOCK_REPLY, tool_call_id=call.get("id") or "", name=call.get("name"),
                           status="error")

    def wrap_tool_call(self, request, handler):
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._refusal(request) or await handler(request)


def staff_last_lock() -> StaffLastLock:
    return StaffLastLock()


# Import's catalog-writer pauses before every promote_research: staff approve each write, and answer a
# funder's case 3 or 4 questions on the same card (docs/features/2026-10-08-import-coverage-report.md).
PROMOTE_TOOL = "promote_research"


class SaveQuestions(HumanInTheLoopMiddleware):
    """Pauses every promote_research, carrying its questions, planned rows and coverage on the request.

    The person's answers arrive as an `edit` whose args hold `decisions`. Decisions the model wrote
    itself are dropped: only a person's edit can set them.
    """

    def __init__(self) -> None:
        super().__init__(interrupt_on={PROMOTE_TOOL: {
            "allowed_decisions": ["approve", "edit", "reject"],
            "description": lambda call, state, runtime: self._describe(call),
        }})
        # tool_call id -> its preview, only for the length of one after-model step.
        self._previews: dict[str, dict] = {}

    def _describe(self, call) -> str:
        n = len(self._previews.get(call.get("id"), {}).get("questions", []))
        what = call["args"].get("slug") or "every researched organisation"
        return f"Approve writing {what} to the catalog" + (f" ({n} question(s))" if n else "")

    def _create_action_and_config(self, tool_call, config, state, runtime):
        action, review = super()._create_action_and_config(tool_call, config, state, runtime)
        preview = self._previews.get(tool_call.get("id"), {})
        action["questions"] = preview.get("questions", [])  # type: ignore[typeddict-unknown-key]
        action["planned"] = preview.get("planned", [])  # type: ignore[typeddict-unknown-key]
        action["coverage"] = preview.get("coverage", "")  # type: ignore[typeddict-unknown-key]
        return action, review

    async def aafter_model(self, state, runtime):
        last = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        calls = [c for c in (last.tool_calls if last else []) if c["name"] == PROMOTE_TOOL]
        for call in calls:
            slug = call["args"].get("slug") or ""
            # An empty slug sweeps everything: still approved, but its questions are held instead.
            self._previews[call["id"]] = await write_preview(slug) if slug else {}
        try:
            return self.after_model(state, runtime)
        finally:
            for call in calls:
                self._previews.pop(call["id"], None)

    async def awrap_tool_call(self, request, handler):
        if request.tool_call["name"] != PROMOTE_TOOL:
            return await handler(request)
        edit = self._reviewer_edit(request)
        answers = (edit or {}).get("args", {}).get("decisions")
        args = {**request.tool_call["args"], "decisions": answers if isinstance(answers, dict) else {}}
        return await handler(request.override(tool_call={**request.tool_call, "args": args}))

    def wrap_tool_call(self, request, handler):
        if request.tool_call["name"] != PROMOTE_TOOL:
            return handler(request)
        args = {**request.tool_call["args"], "decisions": {}}
        return handler(request.override(tool_call={**request.tool_call, "args": args}))


def save_questions() -> SaveQuestions:
    return SaveQuestions()

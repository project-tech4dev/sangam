"""Middleware for the deep agent."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace

from langchain.agents.middleware import (
    AgentMiddleware,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
    ToolErrorMiddleware,
    after_agent,
    before_model,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agent.audit import CAVEAT_PREFIX, audit_turn
from app.agent.tools.sql.errors import FAILED_PREFIX, REJECTED_PREFIX
from app.integrations.tracing import score_answer

logger = logging.getLogger(__name__)

# Failed db_query attempts allowed per user question. The system prompt is told the same number so the model
# stops gracefully first; this is the deterministic backstop for when it does not.  Only db_query counts.
MAX_SQL_ATTEMPTS = 5

COUNTED_TOOL = "db_query"
_FAILURE_PREFIXES = (FAILED_PREFIX, REJECTED_PREFIX)

# Bulky old result grids are dead weight once the model has read them, but the
# most recent few are what a follow-up question refers back to.
TOOL_RESULT_CLEAR_TRIGGER_TOKENS = 60_000
TOOL_RESULTS_KEPT = 5
# Clearing grows in steps of this size, so the cleared set (and the cached prefix) moves once per step.
TOOL_RESULTS_CLEAR_STEP = 20_000
# compare_fit is bounded and is what the write-up reads; clearing it made the model call it again.
NEVER_CLEARED = ("compare_fit",)

_GIVE_UP = (
    "I tried a few ways to query this but couldn't get a working result. Could you "
    "rephrase the question, or tell me which table it should come from? You can also "
    "ask me what data is available."
)


def count_failed_sql_attempts(messages: list[BaseMessage]) -> int:
    """Failed db_query calls since the user's most recent message."""
    failures = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if (
            isinstance(message, ToolMessage)
            and message.name == COUNTED_TOOL
            and isinstance(message.content, str)
            and message.content.startswith(_FAILURE_PREFIXES)
        ):
            failures += 1
    return failures


@before_model(can_jump_to=["end"])
def sql_retry_limiter(state, runtime):
    """Stop the loop after MAX_SQL_ATTEMPTS failed queries for one question."""
    failures = count_failed_sql_attempts(state["messages"])
    if failures < MAX_SQL_ATTEMPTS:
        return None
    logger.info("sql retry budget exhausted after %d failed db_query calls", failures)
    return {"messages": [AIMessage(content=_GIVE_UP)], "jump_to": "end"}


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


def answer_audit(model_spec: str):
    """Append a caveat when a cheap second opinion finds a problem with the answer."""

    @after_agent(name="answer_audit")
    def _audit(state, runtime):
        verdict = audit_turn(state["messages"], model_spec)
        if verdict is None:
            return None
        # Scored either way: a dashboard showing only the failures cannot tell
        # you whether the rate is improving.
        score_answer(
            "answer_audit",
            1.0 if verdict.verdict == "ok" else 0.0,
            comment=verdict.caveat,
        )
        if verdict.verdict != "warn" or not verdict.caveat:
            return None
        logger.info("answer audit raised a caveat: %s", verdict.caveat)
        return {"messages": [AIMessage(content=f"{CAVEAT_PREFIX} {verdict.caveat}")]}

    return _audit


# The researcher reads untrusted pages and the staff workbooks; once it has seen a staff row, no
# outbound tool runs, so an injected instruction cannot carry a row out in a URL or query.
STAFF_TOOL = "read_source_rows"
# An allowlist, so an outbound tool added to the researcher later is closed by default.
OPEN_AFTER_STAFF = frozenset({STAFF_TOOL, "save_research", "read_document_pages", "research_goals",
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
SAVE_TOOL = "promote_research"


class SaveQuestions(HumanInTheLoopMiddleware):
    """Pauses every promote_research, carrying its questions, planned rows and coverage on the request.

    The person's answers arrive as an `edit` whose args hold `decisions`. Decisions the model wrote
    itself are dropped: only a person's edit can set them.
    """

    def __init__(self) -> None:
        super().__init__(interrupt_on={SAVE_TOOL: {
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
        from app.ingest.tools.catalog_tools import write_preview  # the ingest package imports this module

        last = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        calls = [c for c in (last.tool_calls if last else []) if c["name"] == SAVE_TOOL]
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
        if request.tool_call["name"] != SAVE_TOOL:
            return await handler(request)
        edit = self._reviewer_edit(request)
        answers = (edit or {}).get("args", {}).get("decisions")
        args = {**request.tool_call["args"], "decisions": answers if isinstance(answers, dict) else {}}
        return await handler(request.override(tool_call={**request.tool_call, "args": args}))

    def wrap_tool_call(self, request, handler):
        if request.tool_call["name"] != SAVE_TOOL:
            return handler(request)
        args = {**request.tool_call["args"], "decisions": {}}
        return handler(request.override(tool_call={**request.tool_call, "args": args}))


def save_questions() -> SaveQuestions:
    return SaveQuestions()

"""Middleware for the deep agent."""

from __future__ import annotations

import logging

from langchain.agents.middleware import (
    AgentMiddleware,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
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
TOOL_RESULT_CLEAR_TRIGGER_TOKENS = 40_000
TOOL_RESULTS_KEPT = 5

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


def clear_old_tool_results() -> ContextEditingMiddleware:
    """Drop bulky old tool output from the request once context grows large."""
    return ContextEditingMiddleware(
        edits=[
            ClearToolUsesEdit(
                trigger=TOOL_RESULT_CLEAR_TRIGGER_TOKENS,
                keep=TOOL_RESULTS_KEPT,
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


# Import's catalog-writer asks before promote_research writes a funder's case 3 or 4 findings
# (docs/features/2026-10-08-import-update-or-ask.md). LangChain's own middleware does the pausing,
# so the frontend reads the same HITLRequest shape every other Import pause uses.
SAVE_TOOL = "promote_research"


class SaveQuestions(HumanInTheLoopMiddleware):
    """Pauses promote_research only when its funder has questions, and carries them on the request.

    The person's answers arrive as an `edit` whose args hold `decisions`. Decisions the model wrote
    itself are dropped: only a person's edit can set them.
    """

    def __init__(self) -> None:
        super().__init__(interrupt_on={SAVE_TOOL: {
            "allowed_decisions": ["approve", "edit", "reject"],
            "description": lambda call, state, runtime: self._describe(call),
            "when": lambda request: bool(self._questions.get(request.tool_call.get("id"))),
        }})
        # tool_call id -> its questions, only for the length of one after-model step.
        self._questions: dict[str, list[dict]] = {}

    def _describe(self, call) -> str:
        n = len(self._questions.get(call.get("id"), []))
        return f"{n} question(s) before {call['args'].get('slug')} is saved"

    def _create_action_and_config(self, tool_call, config, state, runtime):
        action, review = super()._create_action_and_config(tool_call, config, state, runtime)
        action["questions"] = self._questions.get(tool_call.get("id"), [])  # type: ignore[typeddict-unknown-key]
        return action, review

    async def aafter_model(self, state, runtime):
        from app.ingest.tools.catalog_tools import open_questions  # the ingest package imports this module

        last = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        calls = [c for c in (last.tool_calls if last else []) if c["name"] == SAVE_TOOL]
        for call in calls:
            slug = call["args"].get("slug") or ""
            # An empty slug sweeps everything and is never asked: its questions are held instead.
            self._questions[call["id"]] = await open_questions(slug) if slug else []
        try:
            return self.after_model(state, runtime)
        finally:
            for call in calls:
                self._questions.pop(call["id"], None)

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

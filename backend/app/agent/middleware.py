"""Middleware for the deep agent."""

from __future__ import annotations

import logging

from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
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

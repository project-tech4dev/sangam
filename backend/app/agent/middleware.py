"""Middleware for the deep agent.

Two concerns, both about what happens when a turn goes wrong rather than right.
"""

from __future__ import annotations

import logging

from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    before_model,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agent.tools.sql.errors import FAILED_PREFIX, REJECTED_PREFIX

logger = logging.getLogger(__name__)

# Failed db_query attempts allowed per user question. The system prompt is told
# the same number so the model stops gracefully first; this is the deterministic
# backstop for when it does not.
#
# Only db_query counts. Discovery calls (db_describe_table, db_profile_column)
# routinely take two or three tries against an unfamiliar schema, and spending
# the SQL budget on them is what forced Dalgo to raise theirs from 3 to 5. The
# graph's recursion_limit is the backstop for a model looping on discovery.
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
    """Failed db_query calls since the user's most recent message.

    The reset at each HumanMessage is the point: the budget is per question, not
    per conversation, or a long session would arrive at its sixth question with
    nothing left.
    """
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
    """Stop the loop after MAX_SQL_ATTEMPTS failed queries for one question.

    Must run first in the middleware list: it can jump to the end, and a hook
    that jumps has to get there before the ones that do work.
    """
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

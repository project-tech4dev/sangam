"""Middleware for the deep agent."""

from __future__ import annotations

import logging

from langchain.agents.middleware import (
    AgentMiddleware,
    after_agent,
    before_model,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agent.audit import CAVEAT_PREFIX, audit_turn
from app.agent.tools.sql.errors import (
    FAILED_PREFIX,
    PROFILE_FAILED_PREFIX,
    PROFILE_REJECTED_PREFIX,
    REJECTED_PREFIX,
)
from app.integrations.tracing import score_answer

logger = logging.getLogger(__name__)

# Failed SQL attempts allowed per user question. The system prompt is told the same number so the model
# stops gracefully first; this is the deterministic backstop for when it does not.
MAX_SQL_ATTEMPTS = 5

# A wrong column in db_profile_column is the same failed attempt as in db_query, so both count.
COUNTED = {
    "db_query": (FAILED_PREFIX, REJECTED_PREFIX),
    "db_profile_column": (PROFILE_FAILED_PREFIX, PROFILE_REJECTED_PREFIX),
}


_GIVE_UP = (
    "I tried a few ways to query this but couldn't get a working result. Could you "
    "rephrase the question, or tell me which table it should come from? You can also "
    "ask me what data is available."
)


def count_failed_sql_attempts(messages: list[BaseMessage]) -> int:
    """Failed db_query and db_profile_column calls since the user's most recent message."""
    failures = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if (
            isinstance(message, ToolMessage)
            and message.name in COUNTED
            and isinstance(message.content, str)
            and message.content.startswith(COUNTED[message.name])
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


_CAPPED = (
    "I've spent the steps I allow myself on one question without finishing it. Could you ask a narrower "
    "question, or one part of it at a time?"
)


def _this_turn(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The messages since the user's most recent one."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[i + 1:]
    return messages


def model_call_cap(limit: int):
    """End a turn that has made `limit` model calls: a runaway question stops here, not at recursion_limit."""

    @before_model(can_jump_to=["end"], name="ModelCallCap")
    def _cap(state, runtime):
        calls = sum(isinstance(m, AIMessage) for m in _this_turn(state["messages"]))
        if calls < limit:
            return None
        logger.info("model call cap reached after %d calls", calls)
        return {"messages": [AIMessage(content=_CAPPED)], "jump_to": "end"}

    return _cap


# compare_fit's own description allows a second call, for weak funders in full; four calls is the trace 5bfdbc85 loop.
MAX_COMPARE_FIT_CALLS = 3
COMPARE_FIT = "compare_fit"


def _fit_key(args: dict) -> tuple:
    ids = args.get("funder_ids")
    return args.get("org_id"), tuple(sorted(ids)) if isinstance(ids, list) else ids


def compare_fit_refusal(messages: list[BaseMessage], call: dict) -> str | None:
    """Why this compare_fit call is refused: the same arguments again this turn, or one call too many."""
    seen: list[tuple] = []
    for message in _this_turn(messages):
        for tc in getattr(message, "tool_calls", None) or []:
            if tc["name"] != COMPARE_FIT:
                continue
            if tc["id"] == call.get("id"):
                if _fit_key(tc["args"]) in seen:
                    return ("compare_fit refused a repeat: it already ran with these arguments this turn. "
                            "Answer from that result; it has not changed.")
                if len(seen) >= MAX_COMPARE_FIT_CALLS:
                    return (f"compare_fit refused: {MAX_COMPARE_FIT_CALLS} calls is the most for one question. "
                            "Answer from the results you have.")
                return None
            seen.append(_fit_key(tc["args"]))
    return None


class CompareFitBudget(AgentMiddleware):
    """Refuses a repeated or surplus compare_fit in code, where rule 14 only asks."""

    def _refusal(self, request) -> ToolMessage | None:
        call = request.tool_call
        if call.get("name") != COMPARE_FIT:
            return None
        state = request.state
        messages = state["messages"] if isinstance(state, dict) else state.messages
        why = compare_fit_refusal(messages, call)
        return ToolMessage(content=why, tool_call_id=call.get("id") or "", name=COMPARE_FIT, status="error") \
            if why else None

    def wrap_tool_call(self, request, handler):
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._refusal(request) or await handler(request)


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

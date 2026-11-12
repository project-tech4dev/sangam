"""A cheap second opinion on the answer, after it has been given."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agentkit.models import resolve_model

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024  # room for a little thinking before the verdict

# Prefix of the caveat the audit used to append (#322). Threads saved before then still hold one as a second
# AIMessage, so anything reading a turn's final answer must keep skipping it.
CAVEAT_PREFIX = "\u26a0\ufe0f"
_EXECUTED = re.compile(r"^executed: (.+)$", re.MULTILINE)
_JSON = re.compile(r"\{.*\}", re.DOTALL)

PROMPT = """You are auditing a data assistant's answer AFTER it was given. Report problems \
that would make the answer WRONG. Ignore style, tone and formatting.

Question: {question}

SQL that ran:
{sql}

What the query returned (first rows):
{result}

The answer given:
{answer}

Check exactly these four things:
1. GRAIN — if the question asks "how many <entities>", does the SQL count that entity, or is \
it counting rows of something else (one row per grant when the question was about orgs)?
2. FILTERS — is every condition in the question (place, status, date range) present in the SQL?
3. FALSE ZERO — if the result is empty or zero, could the filter VALUE be wrong rather than \
the data being absent?
4. NUMBERS — do the figures stated in the answer match the rows returned?

Return ONLY JSON, no prose:
{{"verdict": "ok"}} if the answer is sound, or
{{"verdict": "warn", "caveat": "one short sentence a reader needs to know"}}"""


@dataclass(frozen=True, slots=True)
class Audit:
    verdict: str
    caveat: str | None = None


def executed_sql(message: ToolMessage) -> list[str]:
    """The SQL a db_query ran: its artifact, or the `executed:` line a failure and older results carry."""
    artifact = message.artifact if isinstance(message.artifact, dict) else {}
    if artifact.get("sql"):
        return [artifact["sql"]]
    return _EXECUTED.findall(message.content) if isinstance(message.content, str) else []


def collect_turn(messages: list[BaseMessage]) -> tuple[str, list[str], str, str]:
    """(question, SQL that ran, last result block, final answer) for this turn."""
    question, sql, result, answer = "", [], "", ""
    for message in messages:
        if isinstance(message, HumanMessage):
            question, sql, result, answer = message.text, [], "", ""
        elif isinstance(message, ToolMessage) and isinstance(message.content, str):
            if message.name == "db_query":
                sql.extend(executed_sql(message))
                result = message.content
        elif isinstance(message, AIMessage) and not message.tool_calls:
            # .text, not .content: Claude answers in content blocks, which a str-only check skipped.
            text = message.text
            if text.strip() and not text.startswith(CAVEAT_PREFIX):
                answer = text
    return question, sql, result, answer


def audit_turn(messages: list[BaseMessage], model_spec: str) -> Audit | None:
    """None when the audit is off, not applicable, or unavailable."""
    if not model_spec:
        return None
    question, sql, result, answer = collect_turn(messages)
    if not sql or not answer:
        return None  # nothing SQL-shaped to audit; do not spend a call
    try:
        model = resolve_model(model_spec)
        reply = model.invoke(
            PROMPT.format(
                question=question[:1000],
                sql="\n".join(sql)[:3000],
                result=result[:2000],
                answer=answer[:3000],
            ),
            max_tokens=MAX_TOKENS,
        )
        text = reply.text
        match = _JSON.search(text)
        if not match:
            if reply.response_metadata.get("stop_reason") == "max_tokens":
                logger.warning("answer audit hit max_tokens before its verdict; raise MAX_TOKENS")
            return None
        data = json.loads(match.group(0))
        if data.get("verdict") == "warn":  # a warning without a reason still fails the score
            return Audit("warn", str(data["caveat"]) if data.get("caveat") else None)
        return Audit("ok")
    except Exception:  # a second opinion must never break a turn
        logger.warning("answer audit failed; continuing unaudited", exc_info=True)
        return None

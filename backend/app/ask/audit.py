"""A cheap second opinion on the answer, after it has been given."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.agentkit.models import resolve_model
from app.ask.tools.sql.errors import FAILED_PREFIX, REJECTED_PREFIX

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024  # room for a little thinking before the verdict
RESULT_CHARS = 4000  # per tool result
EVIDENCE_CHARS = 20000  # all of them; Haiku reads this for a fraction of a cent
IST = ZoneInfo("Asia/Kolkata")  # the people asking are in India

# Prefix of the caveat the audit used to append. Older threads still hold one as a second AIMessage,
# so anything reading a turn's final answer must keep skipping it.
CAVEAT_PREFIX = "\u26a0\ufe0f"
_EXECUTED = re.compile(r"^executed: (.+)$", re.MULTILINE)
_JSON = re.compile(r"\{.*\}", re.DOTALL)

PROMPT = """You are auditing a data assistant's answer AFTER it was given. Report problems \
that would make the answer WRONG. Ignore style, tone and formatting.

Today is {today}. A date on or before today is not in the future.

Question: {question}

Every tool result the answer could draw on, in the order they ran:
{evidence}

The answer given:
{answer}

A fact in the answer is supported if ANY result above supports it. compare_fit's scores, tiers \
and statuses are computed in code: they are evidence, not claims to re-judge.

Check exactly these four things:
1. GRAIN — if the question asks "how many <entities>", does the SQL count that entity, or is \
it counting rows of something else (one row per grant when the question was about orgs)?
2. FILTERS — is every condition in the question (place, status, date range) present in the SQL?
3. FALSE ZERO — if the result is empty or zero, could the filter VALUE be wrong rather than \
the data being absent?
4. NUMBERS — do the figures stated in the answer match the results? Count items the answer \
names before saying a count is wrong.

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


@dataclass(slots=True)
class Turn:
    question: str = ""
    evidence: list[str] = field(default_factory=list)  # one block per tool result that returned data
    answer: str = ""


def _evidence(message: ToolMessage) -> str | None:
    """A db_query or compare_fit result worth auditing against; None for a failure or a refusal."""
    content = message.content
    if message.name == "db_query" and not content.startswith((REJECTED_PREFIX, FAILED_PREFIX)):
        sql = "\n".join(executed_sql(message)) or "(not recorded)"
        return f"db_query\nSQL: {sql}\nReturned:\n{content[:RESULT_CHARS]}"
    if message.name == "compare_fit" and not content.startswith(("compare_fit refused", "compare_fit failed")):
        return f"compare_fit\n{content[:RESULT_CHARS]}"
    return None


def collect_turn(messages: list[BaseMessage]) -> Turn:
    """The question, every result that returned data, and the final answer, for this turn only."""
    turn = Turn()
    for message in messages:
        if isinstance(message, HumanMessage):
            turn = Turn(question=message.text)
        elif isinstance(message, ToolMessage) and isinstance(message.content, str):
            if block := _evidence(message):
                turn.evidence.append(block)
        elif isinstance(message, AIMessage) and not message.tool_calls:
            # .text, not .content: Claude answers in content blocks, which a str-only check skipped.
            text = message.text
            if text.strip() and not text.startswith(CAVEAT_PREFIX):
                turn.answer = text
    return turn


def audit_turn(messages: list[BaseMessage], model_spec: str) -> Audit | None:
    """None when the audit is off, not applicable, or unavailable."""
    if not model_spec:
        return None
    turn = collect_turn(messages)
    if not turn.evidence or not turn.answer:
        return None  # no data came back (a refusal, a failure, a schema question): nothing to check
    try:
        model = resolve_model(model_spec)
        reply = model.invoke(
            PROMPT.format(
                today=datetime.now(IST).date().isoformat(),
                question=turn.question[:1000],
                evidence="\n\n".join(turn.evidence)[:EVIDENCE_CHARS],
                answer=turn.answer[:3000],
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

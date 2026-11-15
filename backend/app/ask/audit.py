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

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024  # room for a little thinking before the verdict
RESULT_CHARS = 4000  # per query result
COMPARE_FIT_CHARS = 16000  # a shortlist has up to ten funders in full
FAILURE_CHARS = 300
EVIDENCE_CHARS = 30000  # all of them, newest kept; ~8k tokens, under a tenth of a cent on Haiku
IST = ZoneInfo("Asia/Kolkata")  # the people asking are in India

# Prefix of the caveat the audit used to append. Older threads still hold one as a second AIMessage,
# so anything reading a turn's final answer must keep skipping it.
CAVEAT_PREFIX = "\u26a0\ufe0f"
# compare_fit's refusal for a caller who may not run a match (matching_tools.py); a test holds the two together.
COMPARE_FIT_REFUSED = "compare_fit refused: running a match"
DATA_TOOLS = {"db_query", "db_profile_column", "search_graph", "compare_fit"}
NO_DATA = ("The knowledge graph is not available", "No graph facts found")  # search_graph's empty replies
LARGE_RESULTS = "/large_tool_results/"  # where FilesystemMiddleware moves a result too big to keep inline
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

A fact in the answer is supported if ANY result above supports it. A result marked (no data) failed \
or was empty; an answer may say so. A result marked (cut) has more rows than shown: do not warn that a fact \
is missing when it could be in the part not shown. compare_fit's scores, tiers \
and statuses are computed in code: they are evidence, not claims to re-judge.

Check exactly these four things. Checks 1-3 are about SQL: skip them when no db_query ran.
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
    evidence: list[str] = field(default_factory=list)  # every tool result the answer could draw on, in order
    has_data: bool = False  # at least one result returned rows or a match; only then is there anything to check
    refused: bool = False  # compare_fit refused the caller, so the answer is about access, not data
    answer: str = ""
    paged: set[str] = field(default_factory=set)  # read_file calls that page back an evicted result


def _cut(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    return f"{content[:limit]}\n(cut: {len(content) - limit} more characters not shown)"


def _evidence(message: ToolMessage, turn: Turn) -> str | None:
    """The block the audit reads for one tool result; None for one it has no use for (schema reads, skills)."""
    name, content = message.name, message.content
    if name not in DATA_TOOLS and not (name == "read_file" and message.tool_call_id in turn.paged):
        return None
    if content.startswith(COMPARE_FIT_REFUSED):
        turn.refused = True
    sql = f"\nSQL: {chr(10).join(executed_sql(message)) or '(not recorded)'}" if name == "db_query" else ""
    if content.startswith((f"{name} failed", f"{name} rejected", f"{name} refused", *NO_DATA)):
        return f"{name} (no data){sql}\n{_cut(content, FAILURE_CHARS)}"
    turn.has_data = True
    label = "read_file (a large result paged back)" if name == "read_file" else name
    return f"{label}{sql}\nReturned:\n{_cut(content, COMPARE_FIT_CHARS if name == 'compare_fit' else RESULT_CHARS)}"


def _newest(blocks: list[str]) -> str:
    """Whole blocks, newest first back to the cap: the answer is built mostly from the last results."""
    kept, size = [], 0
    for block in reversed(blocks):
        if kept and size + len(block) > EVIDENCE_CHARS:
            break
        kept.append(block)
        size += len(block) + 2
    dropped = len(blocks) - len(kept)
    return "\n\n".join(([f"({dropped} earlier results not shown)"] if dropped else []) + kept[::-1])


def collect_turn(messages: list[BaseMessage]) -> Turn:
    """The question, every result the answer could draw on, and the final answer, for this turn only."""
    turn = Turn()
    for message in messages:
        if isinstance(message, HumanMessage):
            turn = Turn(question=message.text)
        elif isinstance(message, ToolMessage) and isinstance(message.content, str):
            if block := _evidence(message, turn):
                turn.evidence.append(block)
        elif isinstance(message, AIMessage) and message.tool_calls:
            turn.paged.update(
                call["id"] for call in message.tool_calls
                if call["name"] == "read_file" and str(call["args"].get("file_path", "")).startswith(LARGE_RESULTS)
            )
        elif isinstance(message, AIMessage):
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
    if not turn.has_data or turn.refused or not turn.answer:
        return None  # no data came back, or the answer is a refusal: nothing to check it against
    try:
        model = resolve_model(model_spec)
        reply = model.invoke(
            PROMPT.format(
                today=datetime.now(IST).date().isoformat(),
                question=turn.question[:1000],
                evidence=_newest(turn.evidence),
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

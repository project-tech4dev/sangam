"""Run one golden case through the real agent and score it."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.audit import CAVEAT_PREFIX
from app.agent.build import build_agent
from app.core.config import Settings
from tests.evals.sql_compare import answer_contains_value, gold_satisfied

EXECUTED = re.compile(r"^executed: (.+)$", re.MULTILINE)
CITATION = re.compile(r"\[(org|funder|activity|grant|score|news|graph):([a-zA-Z0-9]+)\]")

# Bounds a runaway case so one bad item cannot burn the whole budget.
RECURSION_LIMIT = 60

# Wall-clock bound per case: a model request that never returns once blocked the
# suite for 7 hours against 2 seconds of CPU.
CASE_TIMEOUT_SECONDS = 180


@dataclass
class CaseResult:
    case_id: str
    answer: str = ""
    agent_sql: list[str] = field(default_factory=list)
    citations: set[str] = field(default_factory=set)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def message_text(message: Any) -> str:
    """The text of a model message, whatever shape the provider used."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


async def run_agent(question: str, settings: Settings) -> tuple[str, list[str], set[str]]:
    """(answer, SQL the agent actually ran, citation markers it emitted)."""
    graph = build_agent(settings, InMemorySaver())
    state = await asyncio.wait_for(
        graph.ainvoke(
            {"messages": [("user", question)]},
            config={
                "configurable": {"thread_id": f"eval-{abs(hash(question))}"},
                "recursion_limit": RECURSION_LIMIT,
            },
        ),
        timeout=CASE_TIMEOUT_SECONDS,
    )

    answer, sqls, cites = "", [], set()
    for message in state["messages"]:
        if isinstance(message, ToolMessage) and isinstance(message.content, str):
            if message.name == "db_query":
                sqls.extend(EXECUTED.findall(message.content))
        elif isinstance(message, AIMessage) and not message.tool_calls:
            text = message_text(message)
            # Skip the audit's appended caveat: it is a second AIMessage, so "the last one" would score the
            # caveat as the answer whenever SQL_AUDIT_MODEL is set.
            if text.strip() and not text.startswith(CAVEAT_PREFIX):
                answer = text
    cites = {f"{k}:{v}" for k, v in CITATION.findall(answer)}
    return answer, sqls, cites


def score(case: dict[str, Any], result: CaseResult, *, gold_rows, agent_rows) -> CaseResult:
    """Apply every gate the case declares. Each failure names what to look at."""
    answer_lower = result.answer.lower()

    if case.get("gold_sql") is not None:
        if agent_rows is not None:
            if not gold_satisfied(gold_rows, agent_rows, result.answer):
                result.failures.append(
                    f"result mismatch\n    gold : {gold_rows[:4]}\n    agent: {agent_rows[:4]}"
                )
        else:
            # The agent answered without db_query — db_profile_column alone is enough for some questions,
            # and the prompt actively tells it to profile before filtering. The gate is whether the ANSWER.
            missing = [
                cell
                for row in gold_rows
                for cell in row
                if cell is not None and not answer_contains_value(result.answer, cell)
            ]
            if missing:
                result.failures.append(
                    f"no query was run and the answer omits gold values: {missing[:6]}"
                )

    if case.get("expected_value") is not None and not answer_contains_value(
        result.answer, case["expected_value"]
    ):
        result.failures.append(f"answer never states {case['expected_value']!r}")

    for marker in case.get("required_citations", []):
        if marker not in result.citations:
            result.failures.append(f"missing citation {marker}; got {sorted(result.citations)}")

    for marker in case.get("forbidden_citations", []):
        kind = marker.split(":")[0]
        if marker.endswith(":*"):
            if any(c.startswith(f"{kind}:") for c in result.citations):
                result.failures.append(f"cited {kind} rows but should have declined")
        elif marker in result.citations:
            result.failures.append(f"cited {marker}, which this question must not return")

    for phrase in case.get("must_mention", []):
        if phrase.lower() not in answer_lower:
            result.failures.append(f"answer never mentions {phrase!r}")

    for phrase in case.get("must_not_mention", []):
        if phrase.lower() in answer_lower:
            result.failures.append(f"answer says {phrase!r}, which it must not")

    if case.get("must_decline") and not _declines(answer_lower):
        result.failures.append("answer does not decline; expected an explicit 'I don't have that'")

    return result


# Phrases that signal explicit non-possession. Deliberately narrow: a loose marker like a bare "no " matches
# almost any sentence, which would make every must_decline case pass whatever the agent said — a false.
_DECLINE_MARKERS = (
    "don't have",
    "do not have",
    "there is no",
    "there's no",
    "there are no",
    "no data",
    "no record",
    "no news",
    "no information",
    "no coverage",
    "not in the database",
    "not in the registry",
    "not in this database",
    "isn't in",
    "is not in",
    "not linked",
    "not available",
    "not present",
    "no such table",
    "does not exist",
    "doesn't exist",
    "cannot",
    "can't",
    "unable to",
    "i won't",
    "i will not",
)


def _declines(answer_lower: str) -> bool:
    return any(marker in answer_lower for marker in _DECLINE_MARKERS)

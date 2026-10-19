"""Run one golden case through the real agent and score it."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.audit import CAVEAT_PREFIX, executed_sql
from app.agent.build import build_agent
from app.core.config import Settings
from app.core.security import DEV_USER, _db_identity, chat_user_id
from app.db.pool import agent_caller, caveats_given
from tests.evals.sql_compare import answer_contains_value, gold_satisfied

CITATION = re.compile(r"\[(org|funder|activity|grant|score|news|graph):([a-zA-Z0-9]+)\]")

# Bounds a runaway case so one bad item cannot burn the whole budget.
RECURSION_LIMIT = 60

# deepagents writes an oversized tool result here; reading it back means the reply did not fit.
LARGE_RESULTS_DIR = "/large_tool_results"

# Wall-clock bound per case: a model request that never returns once blocked the
# suite for 7 hours against 2 seconds of CPU.
CASE_TIMEOUT_SECONDS = 180


@dataclass
class RunStats:
    """What one run cost, counted from its messages; Langfuse prices the tokens."""

    tool_calls: Counter = field(default_factory=Counter)
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    large_result_reads: int = 0
    seconds: float = 0.0

    @property
    def total_tool_calls(self) -> int:
        return sum(self.tool_calls.values())

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "tool_calls": dict(self.tool_calls), "total_tool_calls": self.total_tool_calls}


def run_stats(messages: list[Any]) -> RunStats:
    stats = RunStats()
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        usage = message.usage_metadata
        if usage:
            stats.model_calls += 1
            stats.input_tokens += usage.get("input_tokens", 0)
            stats.output_tokens += usage.get("output_tokens", 0)
            details = usage.get("input_token_details") or {}
            stats.cache_read_tokens += details.get("cache_read", 0) or 0
            stats.cache_creation_tokens += details.get("cache_creation", 0) or 0
        for call in message.tool_calls:
            stats.tool_calls[call["name"]] += 1
            path = str((call.get("args") or {}).get("file_path", ""))
            if call["name"] == "read_file" and path.startswith(LARGE_RESULTS_DIR):
                stats.large_result_reads += 1
    return stats


@dataclass
class AgentRun:
    answer: str
    agent_sql: list[str]
    citations: set[str]
    stats: RunStats


@dataclass
class CaseResult:
    case_id: str
    answer: str = ""
    agent_sql: list[str] = field(default_factory=list)
    citations: set[str] = field(default_factory=set)
    failures: list[str] = field(default_factory=list)
    # Reported, never failing: a slow run is a trend to watch, not a broken answer.
    warnings: list[str] = field(default_factory=list)
    stats: RunStats = field(default_factory=RunStats)

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


async def run_agent(question: str, settings: Settings, *, timeout: float = CASE_TIMEOUT_SECONDS) -> AgentRun:
    """The answer, the SQL the agent actually ran, the citations it emitted and what it cost."""
    graph = build_agent(settings, InMemorySaver())
    # The staff dev user, so the agent reads what the gold SQL (run as the owner) reads.
    agent_caller.set(_db_identity(DEV_USER))
    caveats_given.set(set())
    # compare_fit refuses anyone who may not run a match, and an unset chat user is no one.
    chat_user_id.set(DEV_USER.id)
    state = await asyncio.wait_for(
        graph.ainvoke(
            {"messages": [("user", question)]},
            config={
                "configurable": {"thread_id": f"eval-{abs(hash(question))}"},
                "recursion_limit": RECURSION_LIMIT,
            },
        ),
        timeout=timeout,
    )

    answer, sqls, cites = "", [], set()
    for message in state["messages"]:
        if isinstance(message, ToolMessage) and isinstance(message.content, str):
            if message.name == "db_query":
                sqls.extend(executed_sql(message))
        elif isinstance(message, AIMessage) and not message.tool_calls:
            text = message_text(message)
            # Skip the audit's appended caveat: it is a second AIMessage, so "the last one" would score the
            # caveat as the answer whenever SQL_AUDIT_MODEL is set.
            if text.strip() and not text.startswith(CAVEAT_PREFIX):
                answer = text
    cites = {f"{k}:{v}" for k, v in CITATION.findall(answer)}
    return AgentRun(answer, sqls, cites, run_stats(state["messages"]))


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

    # Budgets that fail are the ones whose breach is a bug; token and total-call counts are only reported.
    for tool, limit in case.get("max_calls", {}).items():
        if result.stats.tool_calls[tool] > limit:
            result.failures.append(f"called {tool} {result.stats.tool_calls[tool]} times; the budget is {limit}")

    if (budget := case.get("max_seconds")) is not None and result.stats.seconds > budget:
        result.warnings.append(f"took {result.stats.seconds}s; the target is {budget}s")

    limit = case.get("max_large_result_reads")
    if limit is not None and result.stats.large_result_reads > limit:
        result.failures.append(
            f"read {LARGE_RESULTS_DIR} {result.stats.large_result_reads} times: a tool reply did not fit"
        )

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

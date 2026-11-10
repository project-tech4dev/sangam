"""Run one Import case through the real Import agent, answering the sources pause as a person would."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.core.config import Settings
from app.core.security import CallerScope, chat_scope
from app.ingest.agent import build_ingest_agent

# One organisation is several minutes of reading, not the 180 s an Ask question gets.
IMPORT_CASE_TIMEOUT_SECONDS = 900
# Public websites and Sangam's library, as "Only public websites" plus the library on the card.
SOURCES = {"web": True, "library": True, "vault_org": None, "vault_docs": [], "staff_paths": []}


class ToolCalls(AsyncCallbackHandler):
    """Every tool call in the run, subagents included, keyed `tool` and `agent.tool` (agent = lc_agent_name)."""

    def __init__(self) -> None:
        self.counts: Counter = Counter()

    async def on_tool_start(self, serialized: dict[str, Any] | None, input_str: str, *, run_id: UUID,
                            metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        name = (serialized or {}).get("name") or kwargs.get("name") or "?"
        agent = (metadata or {}).get("lc_agent_name") or "supervisor"
        self.counts[name] += 1
        self.counts[f"{agent}.{name}"] += 1


@dataclass
class ImportRun:
    summaries: list[dict[str, Any]]
    calls: Counter = field(default_factory=Counter)


def call_failures(case: dict[str, Any], calls: Counter) -> list[str]:
    """A tool called more often than the case allows: the path was wrong even if the row looks right."""
    return [f"called {key} {calls[key]} times; the budget is {limit}"
            for key, limit in case.get("max_calls", {}).items() if calls[key] > limit]


async def run_import(request: str, settings: Settings) -> ImportRun:
    """The ResearchSummary of every researcher the run launched, and every tool call it made."""
    chat_scope.set(CallerScope(user_id=None, is_staff=True))
    graph = build_ingest_agent(settings, InMemorySaver())
    counter = ToolCalls()
    config = {"configurable": {"thread_id": f"import-eval-{abs(hash(request))}"}, "callbacks": [counter]}
    state = await asyncio.wait_for(_until_done(graph, request, config), timeout=IMPORT_CASE_TIMEOUT_SECONDS)
    return ImportRun([s for m in state["messages"] if (s := _summary(m))], counter.counts)


async def _until_done(graph, request: str, config: dict) -> dict:
    state = await graph.ainvoke({"messages": [("user", request)]}, config=config)
    # Each pause is choose_sources; anything else would mean a write this case never asked for.
    for _ in range(3):
        if not state.get("__interrupt__"):
            return state
        paused_on = [a.get("name") for i in state["__interrupt__"] for a in (i.value or {}).get("action_requests", [])]
        if paused_on != ["choose_sources"]:
            raise AssertionError(f"the run paused on {paused_on}, which this case never asked for")
        decision = {"type": "edit", "edited_action": {"name": "choose_sources", "args": SOURCES}}
        state = await graph.ainvoke(Command(resume={"decisions": [decision]}), config=config)
    raise AssertionError("the run kept pausing after its sources were chosen")


def _summary(message: Any) -> dict[str, Any] | None:
    if not (isinstance(message, ToolMessage) and message.name == "task" and isinstance(message.content, str)):
        return None
    try:
        parsed = json.loads(message.content)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) and "fact_count" in parsed else None

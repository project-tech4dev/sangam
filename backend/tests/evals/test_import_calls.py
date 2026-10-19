"""The Import eval's tool-call budgets, on a scripted run: no real model, no database."""

from __future__ import annotations

from collections import Counter

from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app.agent.harness import install
from tests.evals.import_harness import ToolCalls, call_failures


class Scripted(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _call(name: str, args: dict, i: int) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"{name}-{i}"}])


@tool
def read_page(url: str) -> str:
    """Read a page."""
    return "text"


async def test_a_subagents_calls_are_counted_under_its_name():
    install()
    researcher = Scripted(messages=iter([_call("read_page", {"url": "https://a.org"}, 1), AIMessage("done")]))
    supervisor = Scripted(messages=iter([
        _call("task", {"description": "research A", "subagent_type": "entity-researcher"}, 1),
        AIMessage("report"),
    ]))
    graph = create_deep_agent(
        model=supervisor,
        subagents=[{"name": "entity-researcher", "description": "one org", "system_prompt": "research",
                    "tools": [read_page], "model": researcher}],
    )
    counter = ToolCalls()
    await graph.ainvoke({"messages": [("user", "go")]}, config={"callbacks": [counter]})
    assert counter.counts["task"] == 1
    assert counter.counts["entity-researcher.read_page"] == 1
    assert counter.counts["read_page"] == 1


def test_only_a_call_over_its_budget_fails():
    case = {"max_calls": {"task": 2, "run_import_now": 0, "entity-researcher.save_research": 3}}
    assert call_failures(case, Counter({"task": 2, "entity-researcher.save_research": 3})) == []
    assert call_failures(case, Counter({"task": 3, "run_import_now": 1})) == [
        "called task 3 times; the budget is 2",
        "called run_import_now 1 times; the budget is 0",
    ]
    assert call_failures({}, Counter({"task": 9})) == []

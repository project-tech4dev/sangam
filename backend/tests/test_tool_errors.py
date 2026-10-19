"""A tool that raises answers the model instead of ending the run, on every agent and subagent."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ToolErrorMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from app.agent.middleware import tool_errors


def _request(name: str = "db_query"):
    return SimpleNamespace(tool=None, tool_call={"name": name, "id": "call-1", "args": {}})


class TestARaisingToolAnswersTheModel:
    async def test_the_model_sees_the_type_not_the_message(self):
        async def boom(_):
            raise RuntimeError("password=hunter2 at /srv/secret")

        result = await tool_errors().awrap_tool_call(_request(), boom)
        assert isinstance(result, ToolMessage) and result.status == "error"
        assert result.content.startswith("db_query failed: RuntimeError.")
        assert "hunter2" not in result.content

    async def test_a_pause_for_a_person_still_pauses(self):
        async def pause(_):
            raise GraphInterrupt(())

        with pytest.raises(GraphInterrupt):
            await tool_errors().awrap_tool_call(_request("ask_user"), pause)


@pytest.fixture
def stacks(monkeypatch):
    """Every middleware list deepagents compiles, parent and subagent alike."""
    import deepagents.graph
    import deepagents.middleware.subagents

    seen: list[tuple[str, list]] = []
    real = deepagents.graph.create_agent

    def spy(model, **kwargs):
        seen.append((kwargs.get("name") or "main", kwargs["middleware"]))
        return real(model, **kwargs)

    monkeypatch.setattr(deepagents.graph, "create_agent", spy)
    monkeypatch.setattr(deepagents.middleware.subagents, "create_agent", spy)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    return seen


def _count(stack: list) -> int:
    return sum(isinstance(m, ToolErrorMiddleware) for m in stack)


def test_ask_has_the_backstop(stacks):
    from app.agent.build import build_agent
    from app.core.config import Settings

    build_agent(Settings(_env_file=None), None)
    assert [_count(s) for _, s in stacks] == [1]


def test_import_and_each_subagent_have_the_backstop(stacks):
    from app.core.config import Settings
    from app.ingest.agent import build_ingest_agent

    build_ingest_agent(Settings(_env_file=None), None)
    names = {name for name, _ in stacks}
    assert {"entity-researcher", "catalog-writer", "workbook-reader", "vault-reader"} <= names
    assert all(_count(s) == 1 for _, s in stacks), [(n, _count(s)) for n, s in stacks]


def test_pitch_and_its_readers_have_the_backstop(stacks):
    from app.core.config import Settings
    from app.proposals.agent import build_proposal_agent

    build_proposal_agent(Settings(_env_file=None), None)
    assert len(stacks) == 3  # the agent and its two readers
    assert all(_count(s) == 1 for _, s in stacks)

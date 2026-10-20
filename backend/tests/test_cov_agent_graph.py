"""search_graph and the Graphiti client lifecycle, with a fake client in place of Neo4j."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import pytest

from app.agent.tools import graph_tools
from app.core.config import Settings
from app.integrations import graphiti


@pytest.fixture(autouse=True)
def no_client(monkeypatch):
    monkeypatch.setattr(graphiti, "client", None)


class FakeGraph:
    def __init__(self, results=None, error=None):
        self.results, self.error, self.closed, self.indexed = results or [], error, False, False

    async def search(self, query, num_results):
        if self.error:
            raise self.error
        return self.results

    async def build_indices_and_constraints(self):
        self.indexed = True

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("kwargs, expected", [
    ({}, "NEO4J_URI is not set"),
    ({"neo4j_uri": "bolt://x"}, "OPENAI_API_KEY is not set (Graphiti needs it for embeddings/extraction)"),
    ({"neo4j_uri": "bolt://x", "openai_api_key": "k"}, "ok"),
])
def test_graph_status(kwargs, expected):
    assert graphiti.graph_status(Settings(**{"neo4j_uri": "", "openai_api_key": "", **kwargs})) == expected


async def test_open_graph_off_without_config():
    assert await graphiti.open_graph(Settings(neo4j_uri="", openai_api_key="")) is None
    assert graphiti.client is None


async def test_open_graph_builds_indices_and_sets_the_client(monkeypatch):
    built = {}

    def make(uri, user, password):
        built["args"] = (uri, user, password)
        built["g"] = FakeGraph()
        return built["g"]

    fake = ModuleType("graphiti_core")
    fake.Graphiti = make
    monkeypatch.setitem(sys.modules, "graphiti_core", fake)
    settings = Settings(neo4j_uri="bolt://n", neo4j_user="u", neo4j_password="p", openai_api_key="k")
    g = await graphiti.open_graph(settings)
    assert g is built["g"] and g.indexed and graphiti.client is g
    assert built["args"] == ("bolt://n", "u", "p")

    await graphiti.close_graph()
    assert g.closed and graphiti.client is None
    await graphiti.close_graph()  # a second close is a no-op


async def test_search_without_a_graph_says_why(monkeypatch):
    monkeypatch.setattr(graph_tools, "get_settings", lambda: Settings(neo4j_uri="", openai_api_key=""))
    out = await graph_tools.search_graph.ainvoke({"query": "x"})
    assert "not available (NEO4J_URI is not set)" in out


async def test_search_without_a_client_but_configured_gives_no_reason(monkeypatch):
    monkeypatch.setattr(graph_tools, "get_settings",
                        lambda: Settings(neo4j_uri="bolt://x", openai_api_key="k"))
    out = await graph_tools.search_graph.ainvoke({"query": "x"})
    assert out.startswith("The knowledge graph is not available. Answer")


async def test_search_with_no_results(monkeypatch):
    monkeypatch.setattr(graphiti, "client", FakeGraph())
    assert await graph_tools.search_graph.ainvoke({"query": "kabil"}) == "No graph facts found for 'kabil'."


async def test_search_cites_each_edge_with_its_validity(monkeypatch):
    edges = [
        SimpleNamespace(uuid="abcdef0123", fact="A funds B", valid_at=datetime(2024, 1, 2, tzinfo=UTC), invalid_at=None),
        SimpleNamespace(uuid="12345678zz", fact="C ran D", valid_at=datetime(2023, 5, 1, tzinfo=UTC),
                        invalid_at=datetime(2024, 6, 30, tzinfo=UTC)),
        SimpleNamespace(uuid="99999999", fact="E knows F"),
    ]
    monkeypatch.setattr(graphiti, "client", FakeGraph(edges))
    out = (await graph_tools.search_graph.ainvoke({"query": "q"})).splitlines()
    assert out == [
        "[graph:abcdef01] A funds B (valid from 02 Jan 2024, still current)",
        "[graph:12345678] C ran D (valid from 01 May 2023 to 30 Jun 2024)",
        "[graph:99999999] E knows F",
    ]


async def test_search_failure_is_a_string(monkeypatch):
    monkeypatch.setattr(graphiti, "client", FakeGraph(error=RuntimeError("neo4j down")))
    assert await graph_tools.search_graph.ainvoke({"query": "q"}) == "search_graph failed: neo4j down"

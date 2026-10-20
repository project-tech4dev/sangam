"""Lifespan: boot wiring, lazy agent build, the agent routes and the catalog check, all with fakes."""

from __future__ import annotations

import io
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from ag_ui.core import RunStartedEvent
from fastapi import FastAPI

from app.core import lifespan as ls
from app.core.config import Settings
from app.db import pool as db_pool

RUN = {"threadId": "t1", "runId": "r1", "state": {}, "messages": [], "tools": [], "context": [],
       "forwardedProps": {}}


class FakeConn:
    def __init__(self, tables):
        self.tables = tables

    async def execute(self, sql):
        tables = self.tables

        class Cur:
            async def fetchall(self_inner):
                return [{"table_name": t} for t in tables]

        return Cur()


class FakePool:
    def __init__(self, tables=("orgs",)):
        self.tables, self.opened, self.closed = list(tables), False, False

    async def open(self):
        self.opened = True

    async def close(self):
        self.closed = True

    @asynccontextmanager
    async def connection(self):
        yield FakeConn(self.tables)


async def test_verify_sql_catalog_raises_on_drift(monkeypatch, caplog):
    async def drift(conn):
        return ["orgs.name is missing"]

    monkeypatch.setattr(ls.sql_catalog, "verify_against_db", drift)
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match=r"out of sync .*1 problem"):
        await ls._verify_sql_catalog(FakePool())
    assert "orgs.name is missing" in caplog.text


async def test_verify_sql_catalog_logs_undeclared_tables(monkeypatch, caplog):
    async def clean(conn):
        return []

    monkeypatch.setattr(ls.sql_catalog, "verify_against_db", clean)
    monkeypatch.setattr(ls.sql_catalog, "undeclared_tables", lambda names: sorted(names))
    with caplog.at_level(logging.INFO):
        await ls._verify_sql_catalog(FakePool(["brand_new"]))
    assert "brand_new" in caplog.text

    monkeypatch.setattr(ls.sql_catalog, "undeclared_tables", lambda names: [])
    caplog.clear()
    await ls._verify_sql_catalog(FakePool(["orgs"]))
    assert "not readable" not in caplog.text


def test_flush_telemetry_never_raises(monkeypatch, caplog):
    import langfuse

    shut: list[bool] = []
    monkeypatch.setattr(langfuse, "get_client", lambda: SimpleNamespace(shutdown=lambda: shut.append(True)))
    ls._flush_telemetry()
    assert shut == [True]

    def broken():
        raise RuntimeError("no client")

    monkeypatch.setattr(langfuse, "get_client", broken)
    with caplog.at_level(logging.WARNING):
        ls._flush_telemetry()
    assert "Langfuse flush on shutdown failed" in caplog.text


def test_process_age_reads_proc_and_is_none_without_it(monkeypatch):
    files = {"/proc/self/stat": "123 (python3 (x)) " + " ".join(["0"] * 19) + " 500 rest",
             "/proc/uptime": "12.5 3.0"}
    monkeypatch.setattr(ls, "open", lambda path: io.StringIO(files[path]), raising=False)
    monkeypatch.setattr(ls.os, "sysconf", lambda name: 100)
    assert ls._process_age() == pytest.approx(7.5)

    def missing(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(ls, "open", missing, raising=False)
    assert ls._process_age() is None


@pytest.fixture
def builders(monkeypatch):
    import app.agent.build as ask_build
    import app.ingest.agent as ingest_agent
    import app.proposals.agent as proposal_agent
    from app.integrations import tracing

    made: list[dict] = []

    class Agent:
        def __init__(self, **kwargs):
            made.append(kwargs)

    state = {"live": False, "status": "LangSmith tracing OFF"}
    monkeypatch.setattr(ask_build, "build_agent", lambda s, c: "ask")
    monkeypatch.setattr(ingest_agent, "build_ingest_agent", lambda s, c: "ingest")
    monkeypatch.setattr(proposal_agent, "build_proposal_agent", lambda s, c: "proposal")
    monkeypatch.setattr(tracing, "configure_langfuse", lambda s: state["live"])
    monkeypatch.setattr(tracing, "langsmith_status", lambda: state["status"])
    monkeypatch.setattr(tracing, "masking_enabled", lambda: True)
    monkeypatch.setattr(tracing, "SessionScopedAGUIAgent", Agent)
    return state, made


@pytest.mark.parametrize("live, keys, words", [
    (True, True, "Langfuse tracing enabled"),
    (False, True, "configured but NOT tracing"),
    (False, False, "Langfuse tracing disabled"),
])
def test_build_agents_wires_three_graphs_and_logs_tracing(builders, caplog, live, keys, words):
    state, made = builders
    state["live"] = live
    if live:
        state["status"] = "LangSmith tracing on"
    settings = Settings(langfuse_public_key="pk" if keys else "", langfuse_secret_key="sk" if keys else "",
                        recursion_limit=77)
    with caplog.at_level(logging.INFO):
        agents = ls._build_agents(settings, checkpointer=object())
    assert (agents["ask_graph"], agents["ingest_graph"], agents["proposal_graph"]) == ("ask", "ingest", "proposal")
    assert [m["name"] for m in made] == ["sangam_agent", "sangam_ingest", "sangam_proposal"]
    assert all(m["config"] == {"recursion_limit": 77} for m in made)
    assert made[1]["emit_subagent_events"] is True and made[2]["emit_raw_events"] is False
    assert words in caplog.text


async def test_load_agents_is_none_outside_a_lifespan_and_builds_once(monkeypatch):
    import asyncio

    app = FastAPI()
    assert await ls.load_agents(app) is None

    built: list[int] = []

    def build(settings, checkpointer):
        built.append(1)
        return {"ask_graph": "ask"}

    monkeypatch.setattr(ls, "_build_agents", build)
    app.state.checkpointer, app.state.settings = object(), Settings()
    app.state.agents, app.state.agents_lock = None, asyncio.Lock()
    first, second = await asyncio.gather(ls.load_agents(app), ls.load_agents(app))
    assert first is second and built == [1]
    assert await ls.get_graph(app, "ask_graph") == "ask"

    app.state.ingest_graph = "already here"
    assert await ls.get_graph(app, "ingest_graph") == "already here"


async def test_get_graph_without_agents_is_none():
    assert await ls.get_graph(FastAPI(), "ask_graph") is None


async def test_an_agent_route_streams_a_cloned_agents_events(monkeypatch):
    runs: list[str] = []

    class Agent:
        def clone(self):
            return self

        async def run(self, input_data):
            runs.append(input_data.thread_id)
            yield RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)

    async def agents(app):
        return {"/agent": Agent()}

    monkeypatch.setattr(ls, "load_agents", agents)
    app = FastAPI()
    for check in ls.AGENT_ACCESS["/agent"]:
        app.dependency_overrides[check] = lambda: None
    ls._add_agent_route(app, "/agent")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        streamed = await client.post("/agent", json=RUN)
        health = await client.get("/agent/health")
    assert streamed.status_code == 200 and "RUN_STARTED" in streamed.text and runs == ["t1"]
    assert health.json() == {"status": "ok", "agent": {"name": "sangam_agent"}}


@pytest.fixture
def boot(monkeypatch):
    pool = FakePool()
    seen: dict = {"graph": [], "flushed": 0}

    async def verify(p):
        seen["verified"] = p

    async def open_graph(settings):
        seen["graph"].append("open")

    async def close_graph():
        seen["graph"].append("close")

    @asynccontextmanager
    async def checkpointer(p):
        seen["checkpointer_pool"] = p
        yield "saver"

    monkeypatch.setattr(ls, "make_pool", lambda url, size: pool)
    monkeypatch.setattr(ls, "_verify_sql_catalog", verify)
    monkeypatch.setattr(ls.graphiti, "open_graph", open_graph)
    monkeypatch.setattr(ls.graphiti, "close_graph", close_graph)
    monkeypatch.setattr(ls, "open_checkpointer", checkpointer)
    monkeypatch.setattr(ls, "_flush_telemetry", lambda: seen.__setitem__("flushed", seen["flushed"] + 1))
    monkeypatch.setattr(ls, "_process_age", lambda: 1.25)
    return pool, seen


async def test_the_lifespan_opens_everything_and_closes_it(boot):
    pool, seen = boot
    app = FastAPI()
    settings = Settings(langfuse_public_key="pk", langfuse_secret_key="sk")
    async with ls.build_lifespan(settings)(app):
        assert db_pool.pool is pool and pool.opened and seen["verified"] is pool
        assert app.state.checkpointer == "saver" and app.state.agents is None and app.state.settings is settings
        paths = {r.path for r in app.routes}
        assert {"/agent", "/ingest", "/proposal", "/agent/health"} <= paths
        app.state.agents = {"built": True}
    assert db_pool.pool is None and pool.closed and seen["graph"] == ["open", "close"]
    assert seen["flushed"] == 1


async def test_no_flush_when_no_agent_was_built(boot, monkeypatch):
    pool, seen = boot
    monkeypatch.setattr(ls, "_process_age", lambda: None)
    monkeypatch.setattr(ls, "get_settings", lambda: Settings(langfuse_public_key="pk", langfuse_secret_key="sk"))
    async with ls.build_lifespan()(FastAPI()):
        pass
    assert seen["flushed"] == 0 and pool.closed

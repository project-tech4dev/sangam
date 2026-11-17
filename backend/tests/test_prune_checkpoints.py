"""scripts/sql/prune_subagent_checkpoints.sql against real LangGraph checkpoints: a cleaned chat reopens the same."""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.types import Command, interrupt

from tests.conftest import DSN

pytestmark = pytest.mark.integration

SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "sql" / "prune_subagent_checkpoints.sql"


def _graph(saver, *, pause: bool, nesting: str = "node"):
    def work(state):
        if pause:
            interrupt("approve?")
        return {"messages": [("ai", "researched")]}

    sub = StateGraph(MessagesState)
    sub.add_node("work", work)
    sub.add_edge(START, "work")
    compiled = sub.compile()

    async def task(state):
        # deepagents' shape: the subagent runs inside a tool call, under the calling task's namespace.
        return await compiled.ainvoke(state)

    parent = StateGraph(MessagesState)
    parent.add_node("subagent", compiled if nesting == "node" else task)
    parent.add_edge(START, "subagent")
    return parent.compile(checkpointer=saver)


def _prune(thread: str, *, apply: bool, idle_hours: int = 0) -> str:
    out = subprocess.run(
        ["psql", DSN, "-X", "-v", f"thread={thread}", "-v", f"apply={int(apply)}", "-v", f"idle_hours={idle_hours}",
         "-f", "-"],
        input=SCRIPT.read_text(), capture_output=True, text=True, check=True,
    )
    return out.stdout


async def _subagent_rows(conn, thread: str) -> int:
    row = await (await conn.execute(
        "SELECT (SELECT count(*) FROM checkpoints WHERE thread_id = %(t)s AND checkpoint_ns <> '')"
        " + (SELECT count(*) FROM checkpoint_blobs WHERE thread_id = %(t)s AND checkpoint_ns <> '')"
        " + (SELECT count(*) FROM checkpoint_writes WHERE thread_id = %(t)s AND checkpoint_ns <> '') AS n",
        {"t": thread},
    )).fetchone()
    return row["n"]


@pytest.fixture
async def saver():
    if not shutil.which("psql"):
        pytest.skip("psql is not on PATH")
    try:
        async with AsyncPostgresSaver.from_conn_string(DSN) as saver:
            yield saver
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")


@pytest.fixture
async def threads(saver):
    made: list[str] = []
    yield made
    async with saver.conn.cursor() as cur:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            await cur.execute(f"DELETE FROM {table} WHERE thread_id = ANY(%s)", (made,))


@pytest.mark.parametrize("nesting", ["node", "tool"])
async def test_a_finished_thread_loses_its_subagents_and_reopens_the_same(saver, threads, nesting):
    thread = f"prune-test-{uuid4().hex[:8]}"
    threads.append(thread)
    graph = _graph(saver, pause=False, nesting=nesting)
    config = {"configurable": {"thread_id": thread}}
    await graph.ainvoke({"messages": [("user", "go")]}, config)
    before = (await graph.aget_state(config)).values
    assert await _subagent_rows(saver.conn, thread) > 0

    assert "dry run" in _prune(thread, apply=False)
    assert await _subagent_rows(saver.conn, thread) > 0

    _prune(thread, apply=True)
    assert await _subagent_rows(saver.conn, thread) == 0
    assert (await graph.aget_state(config)).values == before


@pytest.mark.parametrize("nesting", ["node", "tool"])
async def test_a_paused_thread_is_untouched_and_still_resumes(saver, threads, nesting):
    thread = f"prune-test-{uuid4().hex[:8]}"
    threads.append(thread)
    graph = _graph(saver, pause=True, nesting=nesting)
    config = {"configurable": {"thread_id": thread}}
    await graph.ainvoke({"messages": [("user", "go")]}, config)
    rows = await _subagent_rows(saver.conn, thread)
    assert rows > 0 and (await graph.aget_state(config)).next

    _prune(thread, apply=True)
    assert await _subagent_rows(saver.conn, thread) == rows
    done = await graph.ainvoke(Command(resume="yes"), config)
    assert done["messages"][-1].content == "researched"


async def test_a_thread_newer_than_the_cutoff_is_untouched(saver, threads):
    thread = f"prune-test-{uuid4().hex[:8]}"
    threads.append(thread)
    await _graph(saver, pause=False).ainvoke({"messages": [("user", "go")]}, {"configurable": {"thread_id": thread}})
    rows = await _subagent_rows(saver.conn, thread)
    _prune(thread, apply=True, idle_hours=6)
    assert await _subagent_rows(saver.conn, thread) == rows > 0


async def test_every_thread_dry_run_deletes_nothing(saver, threads):
    thread = f"prune-test-{uuid4().hex[:8]}"
    threads.append(thread)
    await _graph(saver, pause=False).ainvoke({"messages": [("user", "go")]}, {"configurable": {"thread_id": thread}})
    rows = await _subagent_rows(saver.conn, thread)
    assert "dry run" in _prune("", apply=False)
    assert await _subagent_rows(saver.conn, thread) == rows

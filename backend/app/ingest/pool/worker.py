"""make pool-worker: claim funder_pool rows in rank order and research each with Scout, within the settings' limits."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import time
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import CallerScope, chat_scope
from app.db import pool as db_pool
from app.db.checkpointer import make_pool
from app.ingest.agent import build_ingest_agent
from app.ingest.pool import job, queue
from app.integrations.tracing import configure_langfuse, flush_traces

log = logging.getLogger("funder_pool")

TICK_SECONDS = 60
# One funder is 10-20 min of reading; past this the attempt counts as failed and the row retries.
RUN_TIMEOUT_SECONDS = 1800
# On SIGTERM running jobs get this long before they are cut off and put back to pending.
SHUTDOWN_GRACE_SECONDS = int(os.environ.get("POOL_SHUTDOWN_GRACE_SECONDS", "120"))
# One job peaked near 940 MiB against the container's 2g, so the whole process runs at most this many at once.
MAX_JOBS = int(os.environ.get("POOL_MAX_JOBS", "2"))
# Scout reads the open web and Sangam's library, as "Only public websites" plus the library on the sources card.
SOURCES = {"web": True, "library": True, "vault_org": None, "vault_docs": [], "staff_paths": []}


def request(row: dict[str, Any]) -> str:
    """What a staff member would type into Scout for one pooled funder: research only, no save."""
    signals = row["signals"] or {}
    lines = [f"Research the funder {row['name']} ({row['category'].replace('_', ' ')}), as published by its source."]
    if aliases := signals.get("aliases"):
        lines.append(f"It is also known as: {', '.join(aliases) if isinstance(aliases, list) else aliases}.")
    if parent := signals.get("parent_name"):
        lines.append(f"Its parent is {parent}.")
    if row.get("cin"):
        lines.append(f"Its CIN is {row['cin']}.")
    lines.append("Research this one organisation only and report back. Do not save anything to the catalog.")
    return " ".join(lines)


def summaries(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Each researcher's summary, from the supervisor's task results."""
    found = []
    for m in state.get("messages", []):
        if isinstance(m, ToolMessage) and m.name == "task" and isinstance(m.content, str):
            try:
                parsed = json.loads(m.content)
            except ValueError:
                continue
            if isinstance(parsed, dict) and parsed.get("slug"):
                found.append(parsed)
    return found


class Scout:
    """One Import agent for the worker's life; each row is its own thread."""

    def __init__(self, settings: Settings) -> None:
        self.saver = InMemorySaver()
        self.graph = build_ingest_agent(settings, self.saver)

    async def research(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        chat_scope.set(CallerScope(user_id=None, is_staff=True))
        thread = f"funder-pool-{row['pool_funder_id']}-{row['attempts']}"
        config = {"configurable": {"thread_id": thread}, "metadata": {"langfuse_session_id": thread}}
        try:
            return await asyncio.wait_for(self._until_done(request(row), config), timeout=RUN_TIMEOUT_SECONDS)
        finally:
            self.saver.delete_thread(thread)  # a finished row's messages would otherwise stay for the worker's life

    async def _until_done(self, text: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        state = await self.graph.ainvoke({"messages": [("user", text)]}, config=config)
        for _ in range(3):
            if not state.get("__interrupt__"):
                return summaries(state)
            paused_on = [a.get("name") for i in state["__interrupt__"]
                         for a in (i.value or {}).get("action_requests", [])]
            if paused_on != ["choose_sources"]:
                raise RuntimeError(f"Scout paused on {paused_on}, which the worker never answers")
            decision = {"type": "edit", "edited_action": {"name": "choose_sources", "args": SOURCES}}
            state = await self.graph.ainvoke(Command(resume={"decisions": [decision]}), config=config)
        raise RuntimeError("Scout kept pausing after its sources were chosen")


async def run_one(pool: Any, row: dict[str, Any], research: job.Research) -> None:
    started = time.monotonic()
    try:
        status, error = await job.process(pool, row, research)
    except asyncio.CancelledError:
        async with pool.connection() as conn:
            await queue.finish(conn, row, "pending", error="stopped by worker shutdown", refund=True)
        log.info("finish pool_funder_id=%s status=pending seconds=%.0f error=shutdown",
                 row["pool_funder_id"], time.monotonic() - started)
        raise
    except Exception as exc:  # noqa: BLE001 - one funder's failure never stops the worker
        error = f"{type(exc).__name__}: {exc}"
        async with pool.connection() as conn:
            status = await queue.fail(conn, row, error)
    finally:
        flush_traces()
    log.info("finish pool_funder_id=%s status=%s seconds=%.0f error=%s",
             row["pool_funder_id"], status, time.monotonic() - started, error)


async def tick(pool: Any, worker_id: str, research: job.Research, running: set[asyncio.Task]) -> None:
    async with pool.connection() as conn:
        enabled = await queue.enabled_settings(conn)
    claimed = 0
    turn = int(time.time() // TICK_SECONDS) % len(enabled) if enabled else 0
    for setting in enabled[turn:] + enabled[:turn]:  # rotated, so one category cannot hold every slot
        room = MAX_JOBS - len(running)
        if room <= 0:
            break
        try:
            async with pool.connection() as conn:
                rows = await queue.claim(conn, setting["category"], worker_id, room)
        except Exception:  # one category failing must not strand rows another already claimed
            log.exception("claim failed category=%s", setting["category"])
            continue
        for row in rows:  # started straight away: a claimed row with no task would sit running until its lock expires
            log.info("claim pool_funder_id=%s category=%s rank=%s attempt=%s",
                     row["pool_funder_id"], row["category"], row["rank_in_category"], row["attempts"])
            task = asyncio.create_task(run_one(pool, row, research))
            running.add(task)
            task.add_done_callback(running.discard)
        claimed += len(rows)
    log.info("heartbeat enabled=%s running=%d claimed=%d",
             ",".join(s["category"] for s in enabled) or "-", len(running), claimed)


async def main() -> int:
    configure_logging()
    settings = get_settings()
    configure_langfuse(settings)
    pool = make_pool(settings.database_url)
    await pool.open()
    db_pool.pool = pool  # Scout's tools read it through get_pool()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    running: set[asyncio.Task] = set()
    scout: Scout | None = None

    async def research(row: dict[str, Any]) -> list[dict[str, Any]]:
        nonlocal scout
        scout = scout or Scout(settings)  # built on first use, so an idle worker never loads the agent
        return await scout.research(row)

    log.info("start worker=%s", worker_id)
    try:
        while not stop.is_set():
            try:
                await tick(pool, worker_id, research, running)
            except Exception:  # a database blip skips one tick, not the worker
                log.exception("tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                pass
        log.info("stopping: %d running, waiting up to %ss", len(running), SHUTDOWN_GRACE_SECONDS)
        if running:
            _, late = await asyncio.wait(set(running), timeout=SHUTDOWN_GRACE_SECONDS)
            for task in late:
                task.cancel()
            await asyncio.gather(*late, return_exceptions=True)
    finally:
        db_pool.pool = None
        await pool.close()
        flush_traces()
    log.info("stopped worker=%s", worker_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

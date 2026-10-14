"""Application lifespan: everything with a startup and a shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from ag_ui.core.types import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse

from app.agent.tools.sql import catalog as sql_catalog
from app.core.config import Settings, get_settings
from app.core.security import ask_access, chat_access, proposal_chat_access, require_scout
from app.db import pool as db_pool
from app.db.checkpointer import make_pool, open_checkpointer
from app.integrations import graphiti

logger = logging.getLogger(__name__)

AGENT_DESCRIPTION = (
    "Grant-intelligence agent over the sangam Postgres database: "
    "CSO/NGO registry, funder profiles, and rubric-based fit scores."
)
INGEST_DESCRIPTION = (
    "Imports funder data from permitted external sources into the catalog, "
    "matches it against what is already there, and reports what it could not process."
)
PROPOSAL_DESCRIPTION = "Works on one grant proposal with the NGO's team, step by step, inside rules the code checks."
AGENT_NAMES = {"/agent": "sangam_agent", "/ingest": "sangam_ingest", "/proposal": "sangam_proposal"}
# Who may post to each agent, and as whom its tools read. Ask Sangam's SQL runs as the caller; Import keeps
# the owner, since it writes the catalog. A proposal chat is one person's, like an Ask chat.
# A path missing here fails at boot rather than fall back to another.
AGENT_ACCESS = {
    "/agent": (ask_access,),
    "/ingest": (require_scout, chat_access),
    "/proposal": (proposal_chat_access,),
}


def _flush_telemetry() -> None:
    """Best-effort Langfuse flush. Telemetry must never block shutdown."""
    try:
        from langfuse import get_client

        get_client().shutdown()
    except Exception:
        logger.warning("Langfuse flush on shutdown failed", exc_info=True)


def _process_age() -> float | None:
    """Seconds since this process started (Linux only), so a cold start's import time reaches the log."""
    try:
        with open("/proc/self/stat") as stat, open("/proc/uptime") as uptime:
            started = int(stat.read().rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
            return float(uptime.read().split()[0]) - started
    except (OSError, ValueError, IndexError):
        return None


def _build_agents(settings: Settings, checkpointer: Any) -> dict[str, Any]:
    """Every agent-stack import lives here: a REST cold start never pays for deepagents, models or tracing."""
    from app.agent.build import build_agent
    from app.ingest.agent import build_ingest_agent
    from app.integrations.tracing import (
        SessionScopedAGUIAgent,
        configure_langfuse,
        langsmith_status,
        masking_enabled,
    )
    from app.proposals.agent import build_proposal_agent

    # Before build_agent: building the client is what registers the
    # mask, and a handler created first would bind to an unmasked one.
    tracing_live = configure_langfuse(settings)
    ask_graph = build_agent(settings, checkpointer)
    ingest_graph = build_ingest_agent(settings, checkpointer)
    proposal_graph = build_proposal_agent(settings, checkpointer)
    # Not redundant with the graph's own with_config. AG-UI builds each
    # request's config from THIS one, and a config passed at invocation beats
    # the one bound to the graph — see the comment on the test in tests/test_tracing.py.
    config = {"recursion_limit": settings.recursion_limit}

    if tracing_live:
        logger.info(
            "Langfuse tracing enabled: host=%s env=%s query-results=%s",
            settings.langfuse_host,
            os.environ.get("LANGFUSE_TRACING_ENVIRONMENT", "default"),
            "masked" if masking_enabled() else "IN TRACES",
        )
    elif settings.langfuse_enabled:
        logger.warning("Langfuse is configured but NOT tracing — see the error above")
    else:
        logger.info("Langfuse tracing disabled (set LANGFUSE_PUBLIC_KEY/SECRET_KEY to enable)")
    # LangSmith needs no wiring for a LangGraph app: env vars switch the
    # tracer on. It is logged for the same reason Langfuse is — a tracing
    # backend that is quietly off looks exactly like one that is working.
    status = langsmith_status()
    (logger.warning if "DROPPED" in status or "OFF" in status else logger.info)(status)

    return {
        "ask_graph": ask_graph,
        "ingest_graph": ingest_graph,
        "proposal_graph": proposal_graph,
        "/agent": SessionScopedAGUIAgent(
            name=AGENT_NAMES["/agent"], description=AGENT_DESCRIPTION, graph=ask_graph, config=config,
        ),
        # Sangam Import: a separate graph and a separate conversation. It shares
        # the checkpointer, so its threads live beside Ask Sangam's and are told
        # apart by thread_id, not by table.
        "/ingest": SessionScopedAGUIAgent(
            name=AGENT_NAMES["/ingest"], description=INGEST_DESCRIPTION, graph=ingest_graph, config=config,
            # Each researcher's steps arrive tagged with its run, so the board can tell them apart.
            emit_subagent_events=True,
        ),
        # No raw events: the drawer reads messages only, and they were most of an answer's SSE bytes.
        "/proposal": SessionScopedAGUIAgent(
            name=AGENT_NAMES["/proposal"], description=PROPOSAL_DESCRIPTION, graph=proposal_graph, config=config,
            emit_raw_events=False,
        ),
    }


async def load_agents(app: FastAPI) -> dict[str, Any] | None:
    """Every agent, built once on the first request that needs one. None outside a lifespan."""
    state = app.state
    if getattr(state, "agents", None) is None:
        if getattr(state, "checkpointer", None) is None:
            return None
        async with state.agents_lock:
            if state.agents is None:
                started = time.perf_counter()
                # Synchronous on purpose: imports and graph compiles are not safe to move off the loop.
                state.agents = _build_agents(state.settings, state.checkpointer)
                logger.info("Agents built on first use in %.2fs", time.perf_counter() - started)
    return state.agents


async def get_graph(app: FastAPI, name: str) -> Any | None:
    """A compiled graph by name (`ask_graph`, `ingest_graph`, `proposal_graph`), building the agents if needed."""
    graph = getattr(app.state, name, None)
    if graph is None:
        agents = await load_agents(app)
        graph = agents[name] if agents else None
    return graph


def _add_agent_route(app: FastAPI, path: str) -> None:
    """The AG-UI route add_langgraph_fastapi_endpoint registers, minus its need for a built agent."""

    @app.post(path, dependencies=[Depends(check) for check in AGENT_ACCESS[path]])
    async def run_agent(input_data: RunAgentInput, request: Request) -> StreamingResponse:
        agents = await load_agents(request.app)
        # Cloned per request: LangGraphAgent keeps per-run state on the instance.
        agent = agents[path].clone()
        encoder = EventEncoder(accept=request.headers.get("accept"))

        async def events():
            async for event in agent.run(input_data):
                yield encoder.encode(event)

        return StreamingResponse(events(), media_type=encoder.get_content_type())

    @app.get(f"{path}/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "agent": {"name": AGENT_NAMES[path]}}


def build_lifespan(settings: Settings | None = None):
    """Build the lifespan context manager for an app built with `settings`."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = settings or get_settings()
        started = time.perf_counter()
        async with AsyncExitStack() as stack:
            pool = make_pool(resolved.database_url, resolved.db_pool_max_size)
            await pool.open()
            stack.push_async_callback(pool.close)
            db_pool.pool = pool  # shared by agent tools and REST endpoints

            await _verify_sql_catalog(pool)
            connected = time.perf_counter()

            await graphiti.open_graph(resolved)  # no-op (logged) when graph is not configured
            stack.push_async_callback(graphiti.close_graph)

            app.state.settings = resolved
            app.state.checkpointer = await stack.enter_async_context(open_checkpointer(pool))
            app.state.agents = None
            app.state.agents_lock = asyncio.Lock()
            for path in AGENT_NAMES:
                _add_agent_route(app, path)

            age = _process_age()
            logger.info(
                "Sangam backend ready: process age %s, connect+catalog %.2fs, boot %.2fs; "
                "model=%s research-at-once=%d db-pool=%d gate=%d",
                f"{age:.2f}s" if age is not None else "n/a",
                connected - started,
                time.perf_counter() - started,
                resolved.model,
                resolved.max_parallel_research,
                resolved.db_pool_max_size,
                resolved.db_gate_slots,
            )

            yield

            if resolved.langfuse_enabled and app.state.agents is not None:
                _flush_telemetry()
            db_pool.pool = None

    return lifespan


async def _verify_sql_catalog(pool) -> None:
    """Fail the boot if the SQL tool's allowlist disagrees with the database."""
    async with pool.connection() as conn:
        problems = await sql_catalog.verify_against_db(conn)
        if problems:
            for problem in problems:
                logger.error("SQL catalog drift: %s", problem)
            raise RuntimeError(
                f"SQL catalog is out of sync with the database ({len(problems)} problem(s)); "
                "see the errors above"
            )

        rows = await (
            await conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        ).fetchall()
        undeclared = sql_catalog.undeclared_tables({r["table_name"] for r in rows})
        if undeclared:
            # Not an error: a new table stays invisible to the agent until someone adds it to the catalog or
            # to KNOWN_EXCLUDED. Logged so the decision actually gets made.
            logger.info(
                "tables not readable by the SQL tool and not declared as excluded: %s",
                ", ".join(undeclared),
            )

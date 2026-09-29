"""Application lifespan: everything with a startup and a shutdown."""

from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager

from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from fastapi import FastAPI

from app.agent.build import build_agent
from app.agent.tools.sql import catalog as sql_catalog
from app.core.config import Settings, get_settings
from app.db import pool as db_pool
from app.db.checkpointer import make_pool, open_checkpointer
from app.ingest.agent import build_ingest_agent
from app.integrations import graphiti
from app.integrations.tracing import (
    SessionScopedAGUIAgent,
    configure_langfuse,
    langsmith_status,
    masking_enabled,
)

logger = logging.getLogger(__name__)

AGENT_DESCRIPTION = (
    "Grant-intelligence agent over the sangam Postgres database: "
    "CSO/NGO registry, funder profiles, and rubric-based fit scores."
)
INGEST_DESCRIPTION = (
    "Imports funder data from permitted external sources into the catalog, "
    "matches it against what is already there, and reports what it could not process."
)


def _flush_telemetry() -> None:
    """Best-effort Langfuse flush. Telemetry must never block shutdown."""
    try:
        from langfuse import get_client

        get_client().shutdown()
    except Exception:
        logger.warning("Langfuse flush on shutdown failed", exc_info=True)


def build_lifespan(settings: Settings | None = None):
    """Build the lifespan context manager for an app built with `settings`."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = settings or get_settings()
        async with AsyncExitStack() as stack:
            pool = make_pool(resolved.database_url)
            await pool.open()
            stack.push_async_callback(pool.close)
            db_pool.pool = pool  # shared by agent tools and REST endpoints

            await _verify_sql_catalog(pool)

            await graphiti.open_graph(resolved)  # no-op (logged) when graph is not configured
            stack.push_async_callback(graphiti.close_graph)

            # Before build_agent: building the client is what registers the
            # mask, and a handler created first would bind to an unmasked one.
            tracing_live = configure_langfuse(resolved)

            checkpointer = await stack.enter_async_context(open_checkpointer(pool))
            add_langgraph_fastapi_endpoint(
                app=app,
                agent=SessionScopedAGUIAgent(
                    name="sangam_agent",
                    description=AGENT_DESCRIPTION,
                    graph=build_agent(resolved, checkpointer),
                ),
                path="/agent",
            )
            # Sangam Import: a separate graph and a separate conversation. It shares
            # the checkpointer, so its threads live beside Ask Sangam's and are told
            # apart by thread_id, not by table.
            add_langgraph_fastapi_endpoint(
                app=app,
                agent=SessionScopedAGUIAgent(
                    name="sangam_ingest",
                    description=INGEST_DESCRIPTION,
                    graph=build_ingest_agent(resolved, checkpointer),
                ),
                path="/ingest",
            )

            if tracing_live:
                logger.info(
                    "Langfuse tracing enabled: host=%s env=%s query-results=%s",
                    resolved.langfuse_host,
                    os.environ.get("LANGFUSE_TRACING_ENVIRONMENT", "default"),
                    "masked" if masking_enabled() else "IN TRACES",
                )
            elif resolved.langfuse_enabled:
                logger.warning("Langfuse is configured but NOT tracing — see the error above")
            else:
                logger.info("Langfuse tracing disabled (set LANGFUSE_PUBLIC_KEY/SECRET_KEY to enable)")

            # LangSmith needs no wiring for a LangGraph app: env vars switch the
            # tracer on. It is logged for the same reason Langfuse is — a tracing
            # backend that is quietly off looks exactly like one that is working.
            status = langsmith_status()
            (logger.warning if "DROPPED" in status or "OFF" in status else logger.info)(status)
            logger.info("Sangam agent ready: model=%s", resolved.model)

            yield

            if resolved.langfuse_enabled:
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

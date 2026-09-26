"""Application lifespan: everything with a startup and a shutdown.

Opens the connection pool, the optional knowledge graph, the LangGraph
checkpointer, and mounts the AG-UI agent endpoint; unwinds all of it in reverse
on shutdown. Kept out of `main.py` so the application module stays a wiring
manifest rather than a lifecycle implementation.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from fastapi import FastAPI

from app.agent.graph import build_agent
from app.core.config import Settings, get_settings
from app.db import pool as db_pool
from app.db.checkpointer import make_pool, open_checkpointer
from app.integrations import graphiti

logger = logging.getLogger(__name__)

AGENT_DESCRIPTION = (
    "Grant-intelligence agent over the sangam Postgres database: "
    "CSO/NGO registry, funder profiles, and rubric-based fit scores."
)


def _flush_telemetry() -> None:
    """Best-effort Langfuse flush. Telemetry must never block shutdown."""
    try:
        from langfuse import get_client

        get_client().shutdown()
    except Exception:  # noqa: BLE001 - never block shutdown on telemetry
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

            await graphiti.open_graph(resolved)  # no-op (logged) when graph is not configured
            stack.push_async_callback(graphiti.close_graph)

            checkpointer = await stack.enter_async_context(open_checkpointer(pool))
            add_langgraph_fastapi_endpoint(
                app=app,
                agent=LangGraphAGUIAgent(
                    name="sangam_agent",
                    description=AGENT_DESCRIPTION,
                    graph=build_agent(resolved, checkpointer),
                ),
                path="/agent",
            )

            if resolved.langfuse_enabled:
                logger.info("Langfuse tracing enabled: host=%s", resolved.langfuse_host)
            else:
                logger.info("Langfuse tracing disabled (set LANGFUSE_PUBLIC_KEY/SECRET_KEY to enable)")
            logger.info("Sangam agent ready: model=%s", resolved.model)

            yield

            if resolved.langfuse_enabled:
                _flush_telemetry()
            db_pool.pool = None

    return lifespan

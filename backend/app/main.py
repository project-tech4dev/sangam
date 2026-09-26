"""FastAPI application: DB pool + checkpointer lifecycle, AG-UI agent endpoint, REST."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import build_agent
from app.api.router import api_router
from app.core.config import get_settings
from app.db import pool as db_pool
from app.db.checkpointer import make_pool, open_checkpointer
from app.integrations import graphiti

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    async with AsyncExitStack() as stack:
        pool = make_pool(settings.database_url)
        await pool.open()
        stack.push_async_callback(pool.close)
        db_pool.pool = pool  # shared by agent tools and REST endpoints

        await graphiti.open_graph(settings)  # no-op (logged) when graph is not configured
        stack.push_async_callback(graphiti.close_graph)

        checkpointer = await stack.enter_async_context(open_checkpointer(pool))
        agent = build_agent(settings, checkpointer)
        add_langgraph_fastapi_endpoint(
            app=app,
            agent=LangGraphAGUIAgent(
                name="sangam_agent",
                description="Grant-intelligence agent over the sangam Postgres database: "
                "CSO/NGO registry, funder profiles, and rubric-based fit scores.",
                graph=agent,
            ),
            path="/agent",
        )
        if settings.langfuse_enabled:
            logger.info("Langfuse tracing enabled: host=%s", settings.langfuse_host)
        else:
            logger.info("Langfuse tracing disabled (set LANGFUSE_PUBLIC_KEY/SECRET_KEY to enable)")
        logger.info("Sangam agent ready: model=%s", settings.model)
        yield
        if settings.langfuse_enabled:
            try:
                from langfuse import get_client

                get_client().shutdown()  # flush pending trace batches
            except Exception:  # noqa: BLE001 - never block shutdown on telemetry
                logger.warning("Langfuse flush on shutdown failed", exc_info=True)
        db_pool.pool = None


OPENAPI_TAGS = [
    {"name": "orgs", "description": "CSO/NGO registry: profiles, identifiers, sectors, locations"},
    {"name": "funders", "description": "Funder profiles and their fit scores"},
    {"name": "grants", "description": "Actual funding relationships between funders and orgs"},
    {"name": "programs", "description": "Programs run by orgs or funders"},
    {"name": "rfps", "description": "Funding opportunities and org matches (RFP Watch)"},
    {"name": "contacts", "description": "People at orgs and funders"},
    {"name": "scores", "description": "Rubric-based funder-fit assessments and adjustment audit log"},
    {"name": "meta", "description": "Shared vocabularies: tags and locations"},
]

app = FastAPI(title="Sangam API", lifespan=lifespan, openapi_tags=OPENAPI_TAGS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins,
    # None rather than "" — an empty pattern matches every origin.
    allow_origin_regex=get_settings().allowed_origin_regex or None,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

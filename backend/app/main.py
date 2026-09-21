"""FastAPI application: DB pool + checkpointer lifecycle, AG-UI agent endpoint, REST."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, graph
from app.agent.graph import build_agent
from app.api.rest import router as rest_router
from app.config import get_settings
from app.persistence import make_pool, open_checkpointer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    async with AsyncExitStack() as stack:
        pool = make_pool(settings.database_url)
        await pool.open()
        stack.push_async_callback(pool.close)
        db.pool = pool  # shared by agent tools and REST endpoints

        await graph.open_graph(settings)  # no-op (logged) when graph is not configured
        stack.push_async_callback(graph.close_graph)

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
        logger.info("Sangam agent ready: model=%s", settings.model)
        yield
        db.pool = None


app = FastAPI(title="Sangam API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

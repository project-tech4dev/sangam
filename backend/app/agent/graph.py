"""Sangam deep agent: LangGraph deep agent wired for CopilotKit via AG-UI."""

from __future__ import annotations

from copilotkit import CopilotKitMiddleware
from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.models import resolve_model
from app.agent.prompt import SYSTEM_PROMPT
from app.config import Settings
from app.tools.db_tools import get_fit_scores, get_funder, search_orgs
from app.tools.graph_tools import search_graph
from app.tools.web import fetch_url


def build_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    return create_deep_agent(
        model=resolve_model(settings.model),
        tools=[search_orgs, get_funder, get_fit_scores, search_graph, fetch_url],
        middleware=[CopilotKitMiddleware()],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )

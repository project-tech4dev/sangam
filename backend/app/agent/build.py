"""Sangam deep agent: LangGraph deep agent wired for CopilotKit via AG-UI."""

from __future__ import annotations

from copilotkit import CopilotKitMiddleware
from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.models import resolve_model
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.tools.db_tools import get_fit_scores, get_funder, get_grants, search_orgs
from app.agent.tools.graph_tools import search_graph
from app.agent.tools.web import fetch_url
from app.core.config import Settings
from app.integrations.tracing import trace_config


def build_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    agent = create_deep_agent(
        model=resolve_model(settings.model),
        tools=[search_orgs, get_funder, get_grants, get_fit_scores, search_graph, fetch_url],
        middleware=[CopilotKitMiddleware()],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    # Langfuse v3 reads LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST from the env;
    # attaching the handler at graph level traces every run, tool call, and
    # generation without touching the AG-UI endpoint. trace_config() returns
    # just a run name when tracing is off or the SDK cannot load.
    return agent.with_config(trace_config(settings))

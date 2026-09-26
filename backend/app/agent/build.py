"""Sangam deep agent: LangGraph deep agent wired for CopilotKit via AG-UI."""

from __future__ import annotations

from copilotkit import CopilotKitMiddleware
from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.middleware import clear_old_tool_results, sql_retry_limiter
from app.agent.models import resolve_model
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.tools.db_tools import get_fit_scores, get_funder, get_grants, search_orgs
from app.agent.tools.graph_tools import search_graph
from app.agent.tools.sql_tools import (
    db_describe_table,
    db_list_tables,
    db_profile_column,
    db_query,
)
from app.agent.tools.web import fetch_url
from app.core.config import Settings
from app.integrations.tracing import trace_config

# The curated tools first: they are tuned, they carry provenance, and they are
# what the prompt tells the model to reach for. The SQL tools are the escape
# hatch for questions their fixed shapes cannot answer — counts, aggregates,
# rankings, cross-entity joins.
TOOLS = [
    search_orgs,
    get_funder,
    get_grants,
    get_fit_scores,
    search_graph,
    fetch_url,
    db_list_tables,
    db_describe_table,
    db_profile_column,
    db_query,
]


def build_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    agent = create_deep_agent(
        model=resolve_model(settings.model),
        tools=TOOLS,
        # sql_retry_limiter must come first: it can jump to the end of the graph,
        # and a hook that jumps has to run before the ones that do work.
        middleware=[sql_retry_limiter, CopilotKitMiddleware(), clear_old_tool_results()],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    # Langfuse v3 reads LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST from the env;
    # attaching the handler at graph level traces every run, tool call, and
    # generation without touching the AG-UI endpoint. trace_config() returns
    # just a run name when tracing is off or the SDK cannot load.
    return agent.with_config(trace_config(settings))

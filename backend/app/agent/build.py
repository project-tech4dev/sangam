"""Sangam deep agent: LangGraph deep agent wired for CopilotKit via AG-UI."""

from __future__ import annotations

from copilotkit import CopilotKitMiddleware
from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.middleware import answer_audit, clear_old_tool_results, sql_retry_limiter
from app.agent.models import resolve_model
from app.agent.prompt import SYSTEM_PROMPT
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

# The agent reaches the database ONE way: it discovers the schema, then writes a
# SELECT. There used to be four hand-written tools alongside these (search_orgs,
# get_funder, get_grants, get_fit_scores) wrapping fixed queries. They were
# removed because they were a cached query plan rather than a capability, and a
# worse one: asked which organisations work in Assam, search_orgs read only
# orgs.registered_location_id and returned all ten, while the model writing its
# own SQL found org_locations, cross-checked both relationships, and answered
# seven. Two paths to the same rows also meant two places to keep correct — a
# data caveat added to one of them did not reach the other.
TOOLS = [
    db_list_tables,
    db_describe_table,
    db_profile_column,
    db_query,
    search_graph,
    fetch_url,
]


def build_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    middleware = [sql_retry_limiter, CopilotKitMiddleware(), clear_old_tool_results()]
    if settings.sql_audit_model:
        # Off unless configured: a real extra model call per SQL turn.
        middleware.append(answer_audit(settings.sql_audit_model))

    agent = create_deep_agent(
        model=resolve_model(settings.model),
        tools=TOOLS,
        # sql_retry_limiter comes first: it can jump to the end of the graph, and
        # a hook that jumps has to run before the ones that do work.
        middleware=middleware,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    # Langfuse v3 reads LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST from the env;
    # attaching the handler at graph level traces every run, tool call, and
    # generation without touching the AG-UI endpoint. trace_config() returns
    # just a run name when tracing is off or the SDK cannot load.
    #
    # recursion_limit has to be bound here or LangGraph uses its default of 25.
    # Settings carried the value but nothing passed it, which went unnoticed while
    # a question cost one curated tool call; writing SQL costs five to twelve, and
    # every middleware hook is its own graph node on top of that.
    return agent.with_config({**trace_config(settings), "recursion_limit": settings.recursion_limit})

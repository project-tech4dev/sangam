"""Sangam deep agent: LangGraph deep agent wired for CopilotKit via AG-UI."""

from __future__ import annotations

from deepagents import create_deep_agent
from deepagents.backends.state import StateBackend
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.harness import filesystem as filesystem_tools
from app.agent.harness import install as install_harness
from app.agent.middleware import answer_audit, clear_old_tool_results, sql_retry_limiter
from app.agent.models import resolve_model
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.tools.graph_tools import search_graph
from app.agent.tools.match_tools import explain_match, match_funders
from app.agent.tools.profile_tools import find_funders, get_funder, get_org
from app.agent.tools.sql_tools import (
    db_describe_table,
    db_list_tables,
    db_profile_column,
    db_query,
)
from app.agent.tools.web import fetch_url
from app.core.config import Settings
from app.integrations.tracing import trace_config

# Facts come through model-written SQL; judgements of fit and profiles come through the matching engine,
# whose tools read the same bundle its evaluators do — one reader, not a curated second query (R17).
TOOLS = [
    db_list_tables,
    db_describe_table,
    db_profile_column,
    db_query,
    search_graph,
    fetch_url,
    match_funders,
    explain_match,
    get_org,
    get_funder,
    find_funders,
]


def build_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    # Before create_deep_agent: the profile is read while the graph is built,
    # so registering afterwards would leave this agent with the preset's tools.
    install_harness()
    # CopilotKitMiddleware was here: it serves frontend-declared tools, setState and
    # generative UI, none of which this app uses. Removing it cost 4 fewer graph nodes.
    # Replaces the preset's FilesystemMiddleware, which brings eight tools
    # bound to virtual state. read_file is the floor the library enforces.
    middleware = [filesystem_tools(StateBackend()), sql_retry_limiter, clear_old_tool_results()]
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
    # Langfuse v3 reads LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST from the env; attaching the handler at graph
    # level traces every run, tool call, and generation without touching the AG-UI endpoint. trace_config().
    return agent.with_config(
        {
            **trace_config(settings, name="sangam_ask", tags=("ask",)),
            "recursion_limit": settings.recursion_limit,
        }
    )

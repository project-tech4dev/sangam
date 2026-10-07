"""Sangam deep agent: LangGraph deep agent wired for CopilotKit via AG-UI."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.state import StateBackend
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.harness import SKILL_READING_TOOLS
from app.agent.harness import filesystem as filesystem_tools
from app.agent.harness import install as install_harness
from app.agent.middleware import answer_audit, clear_old_tool_results, sql_retry_limiter
from app.agent.models import resolve_model
from app.agent.prompt import render_prompt
from app.agent.tools.graph_tools import search_graph
from app.agent.tools.matching_tools import compare_fit
from app.agent.tools.sql_tools import (
    db_describe_table,
    db_list_tables,
    db_profile_column,
    db_query,
)
from app.agent.tools.web import fetch_url
from app.core.config import Settings
from app.integrations.tracing import trace_config

# The agent reaches the database ONE way: it discovers the schema, then writes a SELECT. There used to be
# four hand-written tools alongside these (search_orgs, get_funder, get_grants, get_fit_scores) wrapping.
# compare_fit is the one exception: funder matching is a fixed checklist, so its queries are fixed too.
TOOLS = [
    db_list_tables,
    db_describe_table,
    db_profile_column,
    db_query,
    search_graph,
    fetch_url,
    compare_fit,
]

# Procedures the supervisor loads on demand; the rules they rely on stay in instructions.md.
SKILLS_DIR = Path(str(files("app.agent") / "skills"))
SKILLS_ROUTE = "/skills/"


def _backend() -> CompositeBackend:
    """Virtual state for everything, real disk for /skills/ alone — read-only, as on Import."""
    # virtual_mode roots it: without it, /skills/../../etc/passwd reads the host. Ask has no auth.
    return CompositeBackend(
        default=StateBackend(),
        routes={SKILLS_ROUTE: FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True)},
    )


def build_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    # Before create_deep_agent: the profile is read while the graph is built,
    # so registering afterwards would leave this agent with the preset's tools.
    install_harness()
    # CopilotKitMiddleware was here: it serves frontend-declared tools, setState and
    # generative UI, none of which this app uses. Removing it cost 4 fewer graph nodes.
    # Replaces the preset's FilesystemMiddleware, which brings eight tools.
    # read_file and ls are what loading a skill needs; nothing that writes.
    backend = _backend()
    middleware = [
        filesystem_tools(backend, keep=SKILL_READING_TOOLS),
        sql_retry_limiter,
        clear_old_tool_results(),
    ]
    if settings.sql_audit_model:
        # Off unless configured: a real extra model call per SQL turn.
        middleware.append(answer_audit(settings.sql_audit_model))

    agent = create_deep_agent(
        model=resolve_model(settings.model),
        tools=TOOLS,
        backend=backend,
        skills=[SKILLS_ROUTE],
        # sql_retry_limiter comes before the hooks that do work: it can jump to the
        # end of the graph. The filesystem only adds tools, so its place is free.
        middleware=middleware,
        system_prompt=render_prompt(settings),
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

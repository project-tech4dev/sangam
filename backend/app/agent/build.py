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
from app.agent.middleware import (
    CompareFitBudget,
    answer_audit,
    clear_old_tool_results,
    model_call_cap,
    sql_retry_limiter,
    tool_errors,
)
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
from app.core.config import Settings
from app.ingest.middleware import cheap_summarizer, fallback
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
    strong = resolve_model(settings.model)
    middleware = [
        filesystem_tools(backend, keep=SKILL_READING_TOOLS),
        tool_errors(),
        sql_retry_limiter,
        model_call_cap(settings.ask_model_call_limit),
        CompareFitBudget(),
        clear_old_tool_results(),
        # Import and Pitch already have both: the next tier when a call fails, and summaries on the cheap tier.
        *fallback(settings.model, settings.research_model),
        cheap_summarizer(strong, resolve_model(settings.utility_model), backend),
    ]
    if settings.sql_audit_model:
        # On by default (SQL_AUDIT_MODEL=off turns it off): one cheap extra model call per SQL turn.
        middleware.append(answer_audit(settings.sql_audit_model))

    agent = create_deep_agent(
        model=strong,
        tools=TOOLS,
        backend=backend,
        skills=[SKILLS_ROUTE],
        # sql_retry_limiter and the model-call cap come before the hooks that do work: both can jump to the
        # end of the graph. The filesystem only adds tools, so its place is free.
        middleware=middleware,
        system_prompt=render_prompt(settings),
        checkpointer=checkpointer,
    )
    # The handler at graph level traces every run, tool call and generation without touching the AG-UI
    # endpoint; see trace_config().
    return agent.with_config(
        {
            **trace_config(settings, name="sangam_ask", tags=("ask",)),
            "recursion_limit": settings.recursion_limit,
        }
    )

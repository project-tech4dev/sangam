"""Sangam Import: a second agent, separate from Ask Sangam in graph and in purpose."""

from __future__ import annotations

from importlib.resources import files

from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.middleware import clear_old_tool_results
from app.agent.models import resolve_model
from app.core.config import Settings
from app.ingest.research import fetch_document, read_document_pages, read_page
from app.ingest.tools import (
    import_run_summary,
    list_import_sources,
    pending_resolutions,
    plan_import,
    run_import_now,
)
from app.integrations.tracing import trace_config

INSTRUCTIONS = (files("app.ingest") / "instructions.md").read_text(encoding="utf-8")

# plan_import before run_import_now: the plan is shown and agreed before anything is written.
TOOLS = [
    list_import_sources,
    plan_import,
    run_import_now,
    import_run_summary,
    pending_resolutions,
    # Research tools, the way the hand-vetted sheets were built: open the page,
    # open the report, read the pages carrying the figures. Each checks the
    # registry and robots.txt before it fetches, so capability does not widen access.
    read_page,
    fetch_document,
    read_document_pages,
]


def build_ingest_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    # No SQL tools by design: this agent proposes typed records, and app/ingest/writer.py
    # is the only thing that writes. Ask Sangam reads; this one imports.
    agent = create_deep_agent(
        model=resolve_model(settings.model),
        tools=TOOLS,
        middleware=[clear_old_tool_results()],
        system_prompt=INSTRUCTIONS,
        checkpointer=checkpointer,
    )
    return agent.with_config({**trace_config(settings), "recursion_limit": settings.recursion_limit})

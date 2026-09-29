"""Sangam Import: a second agent, separate from Ask Sangam in graph and in purpose."""

from __future__ import annotations

from importlib.resources import files

from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.middleware import clear_old_tool_results
from app.agent.models import resolve_model
from app.core.config import Settings
from app.ingest.tools import (
    import_run_summary,
    list_import_sources,
    pending_resolutions,
    run_import_now,
)
from app.integrations.tracing import trace_config

INSTRUCTIONS = (files("app.ingest") / "instructions.md").read_text(encoding="utf-8")

TOOLS = [list_import_sources, run_import_now, import_run_summary, pending_resolutions]


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

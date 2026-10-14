"""Sangam's proposal agent: one shared chat per proposal, beside the steps on screen. It reads and moves steps;
the person writes and answers on screen."""

from __future__ import annotations

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.state import StateBackend
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.harness import filesystem as filesystem_tools
from app.agent.harness import install as install_harness
from app.agent.middleware import clear_old_tool_results
from app.agent.models import resolve_model
from app.core.config import Settings
from app.ingest.middleware import cheap_summarizer, fallback
from app.integrations.tracing import trace_config
from app.proposals.middleware import ProposalContext
from app.proposals.tools.proposal_tools import advance_step, read_proposal
from app.proposals.tools.record_tools import read_match, read_org_record

TOOLS = [read_proposal, advance_step, read_match, read_org_record]

_INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text(encoding="utf-8")
if not _INSTRUCTIONS.strip():
    raise RuntimeError("proposal agent instructions are empty")


def build_proposal_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    install_harness()
    backend = StateBackend()
    strong = resolve_model(settings.model)
    utility = resolve_model(settings.utility_model)
    agent = create_deep_agent(
        model=strong,
        tools=TOOLS,
        backend=backend,
        middleware=[
            # read_file only: the floor FilesystemMiddleware needs, over state that holds nothing of ours.
            filesystem_tools(backend),
            clear_old_tool_results(),
            *fallback(settings.model, settings.research_model),
            cheap_summarizer(strong, utility, backend),
            ProposalContext(),
        ],
        system_prompt=_INSTRUCTIONS,
        checkpointer=checkpointer,
    )
    return agent.with_config({**trace_config(settings, name="sangam_proposal", tags=("proposal",)),
                              "recursion_limit": settings.recursion_limit})

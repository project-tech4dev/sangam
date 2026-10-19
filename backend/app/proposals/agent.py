"""Sangam Pitch, the proposal agent: one private chat per person per proposal, beside the steps on screen. It reads,
keeps the fact list, asks one question at a time and writes each section from the facts."""

from __future__ import annotations

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.state import StateBackend
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.harness import filesystem as filesystem_tools
from app.agent.harness import install as install_harness
from app.agent.middleware import clear_old_tool_results, tool_errors
from app.agent.models import resolve_model
from app.core.config import Settings
from app.ingest.middleware import cheap_summarizer, fallback
from app.ingest.tools.research_tools import (
    fetch_document,
    read_document_pages,
    read_page,
    search_public_sources,
)
from app.ingest.tools.vault_tools import read_vault_document
from app.integrations.tracing import trace_config
from app.proposals import readers
from app.proposals.middleware import ProposalContext, nothing_to_answer
from app.proposals.tools.ledger_tools import add_facts, ask_user
from app.proposals.tools.proposal_tools import advance_step, read_proposal
from app.proposals.tools.reading_tools import (
    list_funder_documents,
    read_brief,
    read_files,
    read_funder_document,
    read_template,
)
from app.proposals.tools.record_tools import read_match, read_org_record
from app.proposals.tools.writing_tools import suggest_edit, write_section

TOOLS = [read_proposal, advance_step, read_match, read_org_record, add_facts, ask_user, read_files, write_section, suggest_edit]
# The readers read_files runs: none asks the person anything, and only public research reads the web.
EVIDENCE_TOOLS = [read_vault_document, read_brief, add_facts]
FUNDER_TOOLS = [read_brief, list_funder_documents, read_funder_document, read_template, add_facts]
PUBLIC_TOOLS = [search_public_sources, read_page, fetch_document, read_document_pages, add_facts]

_INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text(encoding="utf-8")
if not _INSTRUCTIONS.strip():
    raise RuntimeError("proposal agent instructions are empty")


def build_proposal_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    install_harness()
    readers.build(settings, EVIDENCE_TOOLS, FUNDER_TOOLS, PUBLIC_TOOLS)
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
            tool_errors(),
            nothing_to_answer,
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

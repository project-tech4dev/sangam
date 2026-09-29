"""Sangam Import: a second agent, separate from Ask Sangam in graph and in purpose."""

from __future__ import annotations

from importlib.resources import files

from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.middleware import clear_old_tool_results
from app.agent.models import resolve_model
from app.core.config import Settings
from app.ingest.research import (
    fetch_document,
    read_document_pages,
    read_page,
    search_public_sources,
)
from app.ingest.tools import (
    funder_dossier,
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
    funder_dossier,
    search_public_sources,
    read_page,
    fetch_document,
    read_document_pages,
]


# One entity per subagent, each with its own context window. The reason is
# context, not speed: a single broad research turn read three PDFs across twenty
# tool calls and never reached its report, because each document displaced the
# last one's findings. An isolated subagent returns its conclusion, not its
# reading. The main agent decides how many to launch.
RESEARCH_TOOLS = [
    funder_dossier,
    search_public_sources,
    read_page,
    fetch_document,
    read_document_pages,
]

ENTITY_RESEARCHER = {
    "name": "entity-researcher",
    "description": (
        "Researches ONE organisation — a funder or an NGO — from public sources and returns "
        "structured findings with the sentence behind each fact. Launch one per organisation, "
        "in a single message, when several are asked about. It cannot write to the catalog."
    ),
    "mode": "isolated",
    "tools": RESEARCH_TOOLS,
    "system_prompt": (
        "You research exactly ONE organisation and report back. Begin by reading the dossier "
        "for what the catalog already holds, then search, then read the strongest sources you "
        "can reach — a statutory filing or annual report before a news article.\n\n"
        "CONFIRM THE ENTITY BEFORE SPENDING ANY BUDGET. A name can belong to more than one "
        "organisation: KABIL is a livelihoods NGO in Assam and also Khanij Bidesh India "
        "Limited, a Ministry of Mines joint venture. Check that what you found matches what "
        "was asked for — an NGO is not a company, and a foundation is not its parent. If the "
        "strongest hits are a different organisation, say so, name both, and STOP. Researching "
        "the wrong entity thoroughly is worse than researching nothing, because it arrives "
        "looking like an answer.\n\n"
        "Every figure you report carries the sentence that states it and the URL it came from. "
        "Amounts in INR. Fiscal years as FY2024-25. A source marked HELD or a REFUSED reply is "
        "a final answer: report it and move on, never look for another route to it.\n\n"
        "Work to a budget: about eight searches and six documents. When it is spent, report "
        "what you have. Research is not finished when nothing is left to find — it is finished "
        "when the budget is gone or the questions are answered, and a partial answer delivered "
        "is worth more than a complete one the user never sees.\n\n"
        "Return a compact structured summary — identity, identifiers, CSR position by year, "
        "projects, geographies, partners, programmes, metrics, documents — and say plainly "
        "which of those you could not find, and where you stopped. 'Not found' is a result, "
        "and so is 'ran out of budget'. Do not pad either into prose, and never report "
        "anything you did not read."
    ),
}


def build_ingest_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    # No SQL tools by design: this agent proposes typed records, and app/ingest/writer.py
    # is the only thing that writes. Ask Sangam reads; this one imports.
    agent = create_deep_agent(
        model=resolve_model(settings.model),
        tools=TOOLS,
        subagents=[ENTITY_RESEARCHER],
        middleware=[clear_old_tool_results()],
        system_prompt=INSTRUCTIONS,
        checkpointer=checkpointer,
    )
    return agent.with_config({**trace_config(settings), "recursion_limit": settings.recursion_limit})

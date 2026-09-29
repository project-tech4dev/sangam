"""Sangam Import: a second agent, separate from Ask Sangam in graph and in purpose."""

from __future__ import annotations

from importlib.resources import files

from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.harness import install as install_harness
from app.agent.middleware import clear_old_tool_results
from app.agent.models import resolve_model
from app.core.config import Settings
from app.ingest.research import (
    fetch_document,
    read_document_pages,
    read_page,
    save_research,
    search_public_sources,
)
from app.ingest.research_records import PromotionReport, ResearchSummary
from app.ingest.tools import (
    funder_dossier,
    import_run_summary,
    list_import_sources,
    pending_resolutions,
    plan_import,
    promote_research,
    research_goals,
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
    promote_research,
    # Research tools, the way the hand-vetted sheets were built: open the page,
    # open the report, read the pages carrying the figures. Each checks the
    # registry and robots.txt before it fetches, so capability does not widen access.
    funder_dossier,
    research_goals,
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
    research_goals,
    search_public_sources,
    read_page,
    fetch_document,
    read_document_pages,
]

# The researcher saves its own findings; the parent never copies JSON around.
RESEARCHER_TOOLS = [*RESEARCH_TOOLS, save_research]

ENTITY_RESEARCHER = {
    "name": "entity-researcher",
    "description": (
        "Researches ONE organisation — a funder or an NGO — from public sources and returns "
        "structured findings with the sentence behind each fact. Launch one per organisation, "
        "in a single message, when several are asked about. It cannot write to the catalog."
    ),
    "mode": "isolated",
    "tools": RESEARCHER_TOOLS,
    # With a response_format the task tool returns the model's JSON instead of
    # its last message, so the parent and the screen both get structure. It is
    # a SUMMARY, not the findings: those reach the database through
    # save_research, and emitting the whole payload twice is both wasteful and
    # a hard failure when a schema this large is imposed on the final call.
    "response_format": ResearchSummary,
    "system_prompt": (
        "You research exactly ONE organisation and report back.\n\n"
        "START WITH research_goals. It reads the database's own columns and tells you which "
        "fields a fact needs to be storable, which are REQUIRED, and what is already held — so "
        "you research toward the schema instead of writing a profile. State your goals in your "
        "first message, then read funder_dossier for the detail, then search, then read the "
        "strongest sources you can reach: a statutory filing or annual report before a news "
        "article. A field you chase is a field the catalog has somewhere to put.\n\n"
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
        "Finish by calling save_research exactly once — ALWAYS, including when you found "
        "nothing and when you found the wrong organisation. An absence that was looked for "
        "is a result worth keeping, and the next person should not repeat the search to "
        "learn it. Pass everything you found, and pass your goals as `goals` so a partial "
        "run reads as 'eight of fourteen fields' rather than an unexplained stop. Each "
        "finding carries the sentence that states it and the URL it came from; a figure "
        "without its sentence is not a finding and the tool will refuse it. Name the "
        "concepts you looked for and did not find — 'not found' is a result, and so is "
        "'ran out of budget'. Research that is only spoken disappears with the conversation.\n\n"
        "EVERY AMOUNT CARRIES ITS UNIT. An amount is {value, unit, text}: the number as "
        "printed, the unit it is in ('inr', 'lakh' or 'crore'), and the source's own wording. "
        "Do not convert — 'Rs 1,068.03 crore' is value 1068.03, unit 'crore', and saying 1068 "
        "in rupees is an error of ten million. The tool does the arithmetic, once.\n\n"
        "If save_research refuses a finding, it says why: fix that finding and call it again. "
        "A rejected payload is not a reason to give up on the rest.\n\n"
        "Then report back the summary only — slug, status, counts, what you found and what you "
        "did not. The findings are already saved; do not repeat them."
    ),
}


# The second kind of subagent. It researches nothing and cannot: its only
# tools are the promoter and the dossier, so every value it writes came out of
# a saved entity_research row through fixed SQL. What it adds over calling
# promote_research directly is the check — promote, read the catalog back,
# report the difference — and a box on the screen saying which organisation is
# being written and what landed.
CATALOG_WRITER: dict = {
    "name": "catalog-writer",
    "description": (
        "Moves ONE organisation's saved research into the catalog and reports exactly what "
        "landed, what was held back and why. Launch one per organisation after its researcher "
        "has reported. It cannot research and cannot invent a value."
    ),
    "mode": "isolated",
    "tools": [promote_research, funder_dossier],
    "response_format": PromotionReport,
    "system_prompt": (
        "You write ONE organisation's research into the catalog. You do not research: you have "
        "no search or fetch tools, and every value you write comes out of the saved research "
        "row through promote_research. Never state a fact the tools did not give you.\n\n"
        "Three steps, in order:\n\n"
        "1. Call promote_research with the slug you were given. This WRITES.\n"
        "2. Call funder_dossier for the same organisation and read what is actually there now. "
        "A promotion that reports six rows and a dossier that shows none is the failure worth "
        "catching, and it is the only reason you exist rather than a direct tool call.\n"
        "3. Report: the tables written and their row counts, every held-back reason VERBATIM, "
        "and the concepts that stayed research. Set verified only if the dossier agreed.\n\n"
        "Held back is not failure and not loss. A place that is not an Indian state, a name that "
        "resembles an existing funder without matching it, a grant whose recipient is not in "
        "orgs — each is a decision waiting for a person. Pass the reason through word for word "
        "rather than summarising it, because the wording is what tells them what to do.\n\n"
        "If nothing was promoted, say so plainly and say why. rows_written 0 with a reason is a "
        "good report; rows_written 0 with no explanation is a useless one."
    ),
}


def build_ingest_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    # Before create_deep_agent: the profile is read while the graph is built.
    install_harness()
    # The writer calls two tools and formats what they return; it needs no
    # reasoning about sources, so it does not need the model that reads
    # forty-page annual reports. Unset, this is the same model as everything
    # else and nothing changes.
    writer = {**CATALOG_WRITER}
    if settings.utility_model:
        writer["model"] = resolve_model(settings.utility_model)
    # No SQL tools by design: this agent proposes typed records, and app/ingest/writer.py
    # is the only thing that writes. Ask Sangam reads; this one imports.
    agent = create_deep_agent(
        model=resolve_model(settings.model),
        tools=TOOLS,
        subagents=[ENTITY_RESEARCHER, writer],
        middleware=[clear_old_tool_results()],
        system_prompt=INSTRUCTIONS,
        checkpointer=checkpointer,
    )
    # Its own trace name: Ask and Import are different graphs doing different
    # work, and sharing "sangam_agent" made an import indistinguishable from a
    # question in Langfuse.
    return agent.with_config(
        {
            **trace_config(settings, name="sangam_import", tags=("import", "research")),
            "recursion_limit": settings.recursion_limit,
        }
    )

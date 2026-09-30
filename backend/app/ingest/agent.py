"""Sangam Import: a second agent, separate from Ask Sangam in graph and in purpose."""

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
from app.agent.middleware import clear_old_tool_results
from app.agent.models import resolve_model
from app.core.config import Settings
from app.ingest.research_records import PromotionReport, ResearchSummary
from app.ingest.tools.catalog_tools import funder_dossier, promote_research, research_goals
from app.ingest.tools.pipeline_tools import (
    import_run_summary,
    list_import_sources,
    pending_resolutions,
    plan_import,
    run_import_now,
)
from app.ingest.tools.research_tools import (
    fetch_document,
    read_document_pages,
    read_page,
    save_research,
    search_public_sources,
)
from app.integrations.tracing import trace_config


def prompt(name: str) -> str:
    """A subagent's instructions, as markdown beside the code.

    They were forty-line Python string literals, which made every edit a
    diff full of quote marks and \\n. Same loader as instructions.md, so they
    travel the same three paths: the wheel, the image's COPY, and the mount.
    """
    text = (files("app.ingest") / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"subagent prompt is empty: {name}.md")
    return text


INSTRUCTIONS = (files("app.ingest") / "instructions.md").read_text(encoding="utf-8")

# Skills live beside the code and ship with it: inside the ./backend/app mount,
# so an edit appears in the container with no rebuild, and inside the image's
# `COPY app/ app/`, so they deploy with no packaging change.
SKILLS_DIR = Path(str(files("app.ingest") / "skills"))
SKILLS_ROUTE = "/skills/"


def _backend() -> CompositeBackend:
    """Virtual state for everything, real disk for /skills/ alone.

    The model loads a skill by calling read_file on the path the prompt
    printed, so that path has to survive a round trip: ls("/skills/") strips
    the prefix, the routed backend lists its own root, and the composite
    prepends "/skills/" back onto every entry. Nothing else touches disk, and
    no tool that writes exists on this agent at all.
    """
    return CompositeBackend(
        default=StateBackend(),
        routes={SKILLS_ROUTE: FilesystemBackend(root_dir=SKILLS_DIR)},
    )

# Grouped as app/ingest/tools/ is, and in call order within each group.
# plan_import before run_import_now: the plan is shown and agreed before
# anything is written.
TOOLS = [
    # pipeline_tools — the adapter path.
    list_import_sources,
    plan_import,
    run_import_now,
    import_run_summary,
    pending_resolutions,
    # catalog_tools — what Sangam already holds, and the one step that writes to it.
    research_goals,
    funder_dossier,
    promote_research,
    # research_tools — the way the hand-vetted sheets were built: open the page,
    # open the report, read the pages carrying the figures. Each checks the
    # registry and robots.txt before it fetches, so capability does not widen access.
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
    research_goals,
    funder_dossier,
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
    # Isolated subagents inherit nothing (graph.py:701-703), so the sources
    # are declared again here rather than picked up from the parent.
    "skills": [SKILLS_ROUTE],
    # With a response_format the task tool returns the model's JSON instead of
    # its last message, so the parent and the screen both get structure. It is
    # a SUMMARY, not the findings: those reach the database through
    # save_research, and emitting the whole payload twice is both wasteful and
    # a hard failure when a schema this large is imposed on the final call.
    "response_format": ResearchSummary,
    "system_prompt": prompt("entity_researcher"),
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
    "system_prompt": prompt("catalog_writer"),
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
    backend = _backend()
    agent = create_deep_agent(
        model=resolve_model(settings.model),
        tools=TOOLS,
        subagents=[ENTITY_RESEARCHER, writer],
        backend=backend,
        skills=[SKILLS_ROUTE],
        middleware=[filesystem_tools(backend, keep=SKILL_READING_TOOLS), clear_old_tool_results()],
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

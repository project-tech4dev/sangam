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
from app.agent.middleware import clear_old_tool_results, save_questions, staff_last_lock
from app.agent.models import resolve_model
from app.core.config import Settings, get_settings
from app.ingest.middleware import (
    CallerNote,
    ChosenSources,
    DropFilesOnExit,
    EscalateAfterFailedSave,
    ReadingLimit,
    RunSources,
    TickedSources,
    call_limit,
    cheap_summarizer,
    fallback,
    research_rubric,
)
from app.ingest.research_records import PromotionReport, ResearchSummary, VaultSummary, WorkbookEntities
from app.ingest.tools.catalog_tools import (
    compare_with_catalog,
    coverage_report,
    funder_dossier,
    promote_research,
    record_registry_check,
    research_goals,
)
from app.ingest.tools.library_tools import list_library_documents, read_library_document
from app.ingest.tools.pipeline_tools import (
    choose_sources,
    import_run_summary,
    list_import_sources,
    pending_resolutions,
    plan_import,
    read_source_rows,
    read_workbook,
    run_import_now,
)
from app.ingest.tools.research_tools import (
    fetch_document,
    publish_brief,
    read_document_pages,
    read_page,
    save_research,
    search_public_sources,
)
from app.ingest.tools.vault_tools import list_vault_documents, read_vault_document, save_vault_findings
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


def _render(text: str, settings: Settings) -> str:
    """The one substitution instructions.md gets.

    Everywhere else in this repo a prompt is the file on disk, and it stays
    that way here bar this token: how many researchers may run at once is
    bounded by the connection pool, so a number frozen in prose would let
    MAX_PARALLEL_RESEARCH be raised while the agent kept launching eight.
    A plain replace, not .format() — the file is full of literal braces.

    Two callers, deliberately: the module-level INSTRUCTIONS renders from
    get_settings() for tests and tooling, while the graph renders from the
    Settings it was built with. Same value in every real run; a test passing
    its own Settings reaches the graph and not the constant.
    """
    return text.replace("{{MAX_PARALLEL_RESEARCH}}", str(settings.max_parallel_research))


_INSTRUCTIONS_MD = (files("app.ingest") / "instructions.md").read_text(encoding="utf-8")
# Module-level, for the tests and the tooling that read the shipped prompt.
INSTRUCTIONS = _render(_INSTRUCTIONS_MD, get_settings())

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
        # virtual_mode roots it: without it, /skills/../../etc/passwd reads the host.
        routes={SKILLS_ROUTE: FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True)},
    )

# The supervisor's own tools. It researches nothing: one path to a source (a researcher) and one from
# research to the catalog (a writer). Its own writes are a staff registry check and run_import_now's bulk pull.
#
# research_goals is not here either, though the parent could use it: in M5 it
# requires an entity_kind and refuses "unknown", and a supervisor that has not
# read a source can only ever guess "funder".
#
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
    # The run's sources: a person ticks them on one card before anything is read (HITL below).
    choose_sources,
    # catalog_tools — what Sangam already holds; promote_research is the catalog-writer's.
    funder_dossier,
    compare_with_catalog,
    coverage_report,
    # A person's check, recorded on their word; the researcher reads untrusted pages, so not its.
    record_registry_check,
    # save_research publishes the brief it saves; this is only for re-publishing.
    publish_brief,
]


# One entity per subagent, each with its own context window. The reason is
# context, not speed: a single broad research turn read three PDFs across twenty
# tool calls and never reached its report, because each document displaced the
# last one's findings. An isolated subagent returns its conclusion, not its
# reading. The main agent decides how many to launch.
RESEARCH_TOOLS = [
    research_goals,
    funder_dossier,
    # Public documents Sangam already holds, archived.
    list_library_documents,
    read_library_document,
    # Staff-only workbooks: the tool refuses anyone else.
    read_source_rows,
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
    # No "skills" key, deliberately. It had one, and an isolated subagent
    # inherits nothing (graph.py:701-703) so it had to be declared here — but
    # the only skill it could load is an output format, and a researcher
    # produces a ResearchSummary with no prose. Its targets come from
    # research_goals, derived from the schema, which cannot go stale the way a
    # written field list can. Skills are the supervisor's: see docs/SKILLS.md.
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


# The third kind. It reads the picked workbooks and returns the names in them, so the
# parent can launch a researcher per name without ever holding a raw row itself.
# No web tools, so the researcher's staff-last lock has nothing to guard here.
WORKBOOK_READER: dict = {
    "name": "workbook-reader",
    "description": (
        "Reads the team spreadsheets picked on the sources card and returns every organisation "
        "they name, with the cell that names it. Launch it when the request is about everyone in "
        "a file; give it the document ids. It researches nothing and reports no figures."
    ),
    "mode": "isolated",
    "tools": [read_workbook],
    "response_format": WorkbookEntities,
    "system_prompt": prompt("workbook_reader"),
}


# The fourth kind, and the only one that reads an organisation's private files. No web tools: private
# text never shares a context with the open web. It saves its own findings to vault_research and hands
# back concept names and ids only, so the researchers it briefs never see a word of the files.
VAULT_READER: dict = {
    "name": "vault-reader",
    "description": (
        "Reads ONE organisation's own Doc Vault files about one funder or NGO, saves what they say, and "
        "returns which concepts the files answered and which are still missing. Launch it before the "
        "entity-researcher when the person picked Doc Vault files on the sources card. It cannot read the web."
    ),
    "mode": "isolated",
    "tools": [list_vault_documents, read_vault_document, research_goals, save_vault_findings],
    "response_format": VaultSummary,
    "system_prompt": prompt("vault_reader"),
}


# Pages and PDFs past this many tokens go to a file the researcher pages back; the library default is 20k.
RESEARCHER_EVICT_AT = 8_000
# Promote, read back, report: a handful of calls, so a dozen is already a loop.
WRITER_MODEL_CALL_LIMIT = 12

# A person chooses where the run reads from before anything is read; rejecting means public websites only.
INTERRUPT_ON = {
    "choose_sources": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "Choose where this run reads from",
    },
}


def build_ingest_agent(settings: Settings, checkpointer: BaseCheckpointSaver):
    # Before create_deep_agent: the profile is read while the graph is built.
    install_harness()
    # No SQL tools by design: this agent proposes typed records, and app/ingest/writer.py
    # is the only thing that writes. Ask Sangam reads; this one imports.
    backend = _backend()
    # An isolated subagent builds its own middleware stack, so the parent's restricted
    # filesystem never reaches it: unset, both run write_file and delete against /skills/.
    # Neither subagent loads a skill now, so neither gets `ls`. read_file is
    # the floor FilesystemMiddleware refuses to be constructed below, not a
    # capability either of them uses.
    strong = resolve_model(settings.model)
    research_spec = settings.research_model
    utility_spec = settings.utility_model
    research = resolve_model(research_spec)
    utility = resolve_model(utility_spec)
    # Each subagent on its tier (config.py). Each falls back to the next
    # tier when its call fails. The researcher reads to a budget, has its save and summary graded, and
    # moves to the strong model if its save is refused for a malformed payload.
    researcher = {
        **ENTITY_RESEARCHER,
        "model": research,
        "middleware": [
            filesystem_tools(backend, evict_at=RESEARCHER_EVICT_AT),
            # Only what the person chose on the sources card; staff rows last.
            RunSources(),
            staff_last_lock(),
            ReadingLimit(settings.research_page_limit),
            call_limit(settings.research_model_call_limit),
            *([EscalateAfterFailedSave(strong)] if research_spec != settings.model else []),
            *fallback(research_spec, settings.model),
            research_rubric(utility),
            cheap_summarizer(research, utility, backend),
        ],
    }
    # save_questions pauses every promote_research for staff to approve, with a button per open question.
    writer = {
        **CATALOG_WRITER,
        "model": utility,
        "middleware": [
            filesystem_tools(backend),
            save_questions(),
            call_limit(WRITER_MODEL_CALL_LIMIT),
            *fallback(utility_spec, research_spec, settings.model),
        ],
    }
    reader = {
        **WORKBOOK_READER,
        "model": utility,
        "middleware": [filesystem_tools(backend), RunSources(), *fallback(utility_spec, research_spec, settings.model)],
    }
    vault_reader = {
        **VAULT_READER,
        "model": research,
        "middleware": [
            filesystem_tools(backend, evict=False),
            RunSources(),
            DropFilesOnExit(),
            call_limit(settings.research_model_call_limit),
            *fallback(research_spec, settings.model),
        ],
    }
    agent = create_deep_agent(
        model=strong,
        tools=TOOLS,
        subagents=[researcher, writer, reader, vault_reader],
        backend=backend,
        skills=[SKILLS_ROUTE],
        middleware=[
            filesystem_tools(backend, keep=SKILL_READING_TOOLS),
            clear_old_tool_results(),
            *fallback(settings.model, research_spec),
            cheap_summarizer(strong, utility, backend),
            CallerNote(),
            ChosenSources(),
            TickedSources(),
        ],
        system_prompt=_render(_INSTRUCTIONS_MD, settings),
        # deepagents turns this into LangChain's HumanInTheLoopMiddleware: the run pauses on the
        # tool call and resumes with Command(resume={"decisions": [...]}) from the Import screen.
        interrupt_on=INTERRUPT_ON,
        checkpointer=checkpointer,
    )
    # Its own trace name: Ask and Import are different graphs doing different
    # work, and sharing "sangam_agent" made an import indistinguishable from a
    # question in Langfuse.
    return agent.with_config(
        {
            **trace_config(settings, name="sangam_import", tags=("import", "research", research_spec, utility_spec)),
            "recursion_limit": settings.recursion_limit,
        }
    )

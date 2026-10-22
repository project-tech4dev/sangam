"""The readers Sangam Pitch runs from step 2: one per ticked file and one for the funder's side; public research apart.

Code launches them, not the model: which files are pending, the one lock on reading, and each file's status in
`work.readers` are decided here, so "Try again" re-reads only what failed.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.state import StateBackend
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables.config import var_child_runnable_config

from app.agent.harness import filesystem as filesystem_tools
from app.agent.middleware import clear_old_tool_results, tool_errors
from app.agent.models import resolve_model
from app.core.config import Settings
from app.db.pool import get_pool
from app.ingest import run_sources
from app.ingest.middleware import RunSources, fallback
from app.integrations.tracing import propagate_caller, trace_config
from app.proposals import brief, context, research, steps
from app.proposals import facts as fact_rules
from app.proposals import work as work_rules
from app.proposals.middleware import PUBLIC_RUN, PublicGuard, PublicRun, ResearchProgress
from app.repositories import profile_facts
from app.repositories import proposals as repo

logger = logging.getLogger(__name__)

FUNDER = "funder"  # work.readers' key for the funder's side; a file's key is its document id
PUBLIC = "public"  # public research: the problem, the place, government and what worked elsewhere
PLACES = 8
RESEARCHER = "public-researcher"  # the supervisor's one subagent; it launches as many as the proposal needs
UNREADABLE = "UNREADABLE:"  # a reader's last message starts with this when the file had nothing to read
FORM = "FORM"  # ...followed by this when the file is a blank funder's form, which step 2 offers to use as one
ERROR_TEXT = 160
_PROMPTS = Path(__file__).parent / "prompts"


@dataclass
class _Built:
    evidence: Any = None
    funder: Any = None
    public: Any = None  # None without a search key: then public research is simply not run
    brief: Any = None  # writes secondary research's brief, with Anthropic's own web search and fetch
    parallel: int = 1
    trace: dict[str, Any] | None = None


BUILT = _Built()


def build(settings: Settings, evidence_tools: list[Any], funder_tools: list[Any],
          public_tools: list[Any] | None = None) -> None:
    """The readers, built once with the proposal agent, none with a checkpoint. Only public research reads the web."""
    backend = StateBackend()
    research = resolve_model(settings.research_model)

    def reader(tools: list[Any], prompt: str, *guards: Any) -> Any:
        return create_deep_agent(
            model=research,
            tools=tools,
            backend=backend,
            middleware=[
                filesystem_tools(backend, evict=False),
                tool_errors(),
                # A long file is read window by window and its facts saved as it goes, so old windows can go.
                clear_old_tool_results(),
                RunSources(),
                *guards,
                *fallback(settings.research_model, settings.model),
            ],
            system_prompt=(_PROMPTS / prompt).read_text(encoding="utf-8"),
            checkpointer=False,
        ).with_config({"recursion_limit": settings.recursion_limit})

    def supervisor(tools: list[Any]) -> Any:
        """Public research: a supervisor that only splits the work, and researchers it runs at the same time."""
        researcher = {
            "name": RESEARCHER,
            "description": "Researches ONE angle of the public evidence and adds its facts. Launch one per angle, "
                           "all in one message.",
            "mode": "isolated",  # inherits nothing, so it carries every guard itself
            "model": research,
            "tools": tools,
            "middleware": [filesystem_tools(backend, evict=False), tool_errors(), RunSources(), PublicGuard(),
                           *fallback(settings.research_model, settings.model)],
            "system_prompt": (_PROMPTS / "public_researcher.md").read_text(encoding="utf-8"),
        }
        return create_deep_agent(
            model=research,
            tools=[],
            subagents=[researcher],
            backend=backend,
            middleware=[filesystem_tools(backend, evict=False), tool_errors(), ResearchProgress(),
                        *fallback(settings.research_model, settings.model)],
            system_prompt=(_PROMPTS / "public_supervisor.md").read_text(encoding="utf-8"),
            checkpointer=False,
        ).with_config({"recursion_limit": settings.recursion_limit})

    BUILT.evidence = reader(evidence_tools, "evidence_reader.md")
    BUILT.funder = reader(funder_tools, "funder_file_reader.md")
    BUILT.public = supervisor(public_tools) if public_tools and settings.tavily_api_key else None
    try:
        BUILT.brief = brief.bind(research)
    except Exception as exc:  # noqa: BLE001 - a model without server-side search writes no brief
        logger.warning(f"[build] no research brief: {settings.research_model} cannot search ({type(exc).__name__})")
    BUILT.parallel = max(1, settings.max_parallel_research)
    BUILT.trace = trace_config(settings, name="sangam_proposal_reader", tags=("proposal", "reader"))


class Busy(Exception):
    """Someone's readers are still running: the one lock in the feature, on reading only."""

    def __init__(self, reader: dict[str, Any], now: datetime):
        started = datetime.fromisoformat(str(reader["at"]))
        minutes = max(0, int((now - started).total_seconds() // 60))
        who = (reader.get("by") or {}).get("name") or "A teammate"
        super().__init__(f"{who} started reading the files {minutes} min ago; wait until they are read")


def pending(work: dict[str, Any], now: datetime | None = None, *, public: bool = False) -> list[str]:
    """The files and funder not yet done, or public research, which may run again. Each locks alone. Raises Busy."""
    now = now or datetime.now(UTC)
    held = work.get("readers") or {}
    busy = [r for k, r in held.items() if (k == PUBLIC) == public
            and r.get("status") == "running" and not steps.readers_stale(r, now)]
    if busy:
        raise Busy(busy[0], now)
    if public:
        return [PUBLIC]
    keys = [*(str(d) for d in work.get("sources") or []), FUNDER]
    return [k for k in keys if (held.get(k) or {}).get("status") != "done"]


def sources_for(p: context.Current, key: str) -> run_sources.Sources:
    """A file's reader may open that one file; the funder's reader, none of the org's; public research, the web."""
    if key == PUBLIC:
        return run_sources.Sources(web=True)
    if key == FUNDER:
        return run_sources.Sources(web=False)
    return run_sources.Sources(web=False, vault_org=p.org_id, vault_docs=frozenset({int(key)}))


def public_task(p: context.Current, places: list[str], themes: list[str], programmes: list[str],
                sdgs: list[str], ask: dict[str, Any] | None = None) -> str:
    """Public research's task, from the registry's public rows and the match only: never a file or the fact list."""
    where = "; ".join(places) or "no place on record: search at state level, or for India"
    sections = [s for s in context.sections(p.work) if s.code in fact_rules.PUBLIC_SECTIONS]

    def listed(items: list[str]) -> str:
        return "; ".join(items) or "none on record"

    return "\n".join([
        f"Research the public evidence for a grant proposal to {p.funder_name}.",
        f"Never search for {p.org_name}, the organisation writing it.",
        "",
        f"Where it works: {where}",
        f"Its themes: {listed(themes)}",
        f"Its programmes: {listed(programmes)}",
        f"SDGs on record: {listed(sdgs)}",
        "",
        "The sections a fact can serve, each with what a strong answer holds:",
        *(f"- {s.code} {s.label}: {'; '.join(s.strong)}" for s in sections),
        *(_focus_block(ask, research.already_found(p.work)) if ask else []),
    ])


def brief_task(p: context.Current, places: list[str], themes: list[str], programmes: list[str],
               sdgs: list[str], ask: dict[str, Any] | None = None) -> str:
    """The brief's task: places, themes, programmes and SDGs. Never the organisation's name, its files or the facts:
    the brief searches on Anthropic's side, where no guard sees the query."""
    org = fact_rules.norm(p.org_name)

    def listed(items: list[str]) -> str:
        return "; ".join(i for i in items if org not in fact_rules.norm(i)) or "none on record"

    focus = (ask or {}).get("focus") or []
    sites = (ask or {}).get("sites") or []
    return "\n".join([
        f"Secondary research for a grant proposal to {p.funder_name}.",
        "",
        f"Where the work happens: {listed(places) if places else 'no place on record: work at state level, or for India'}",
        f"Themes: {listed(themes)}",
        f"Programmes: {listed(programmes)}",
        f"SDGs on record: {listed(sdgs)}",
        *([f"Look especially into: {'; '.join(focus)}"] if focus else []),
        *([f"Start on these sites: {'; '.join(sites)}"] if sites else []),
    ])


async def _no_brief() -> None:
    return None


def _focus_block(ask: dict[str, Any], found: list[str]) -> list[str]:
    """What the person asked this run to look into: angles and sites, never their own sentences."""
    return [
        "",
        "## Focus of this run",
        *([f"The person asked: {ask['ask']}"] if ask.get("ask") else []),
        *([f"Look into: {'; '.join(ask['focus'])}"] if ask.get("focus") else []),
        *([f"Start on these sites: {'; '.join(ask['sites'])}"] if ask.get("sites") else []),
        *(["", "Already found (look past these, do not add them again):", *(f"- {f}" for f in found)]
          if found else []),
    ]


async def _public_inputs(p: context.Current) -> tuple[list[str], list[str], list[str], list[str]]:
    pool = get_pool()
    org = await profile_facts.org_facts(pool, pool, str(p.org_id))
    if org is None:
        return [], [], [], []
    places = [f"{pl.name}, {pl.state}" if pl.state and pl.state != pl.name else pl.name
              for pl in org.places[:PLACES]]
    if not places and (org.org.district or org.org.state):
        places = [", ".join(v for v in (org.org.district, org.org.state) if v)]
    themes = [f"{t.parent_label} › {t.label}" if t.parent_label else t.label for t in org.tags[:PLACES]]
    return (places, themes, [prog.name for prog in org.programs[:PLACES]],
            [f"{s.code} {s.label}" for s in org.sdgs])


def _sections(p: context.Current) -> str:
    return "\n".join(f"- {s.code} {s.label}: {'; '.join(s.strong)}" for s in context.sections(p.work))


def _task(p: context.Current, key: str, title: str) -> str:
    head = (f"Read what Sangam holds on {p.funder_name}, the funder of this proposal from {p.org_name}."
            if key == FUNDER else
            f"Read document {key}, \"{title}\", for {p.org_name}'s proposal to {p.funder_name}.")
    return f"{head}\n\nThe sections a fact can serve, each with what a strong answer holds:\n{_sections(p)}"


def _reason(text: str) -> str:
    """The screen shows one short sentence of why, not the reader's whole note."""
    first = text.removeprefix(UNREADABLE).strip().split("\n")[0]
    return re.split(r"(?<=\.)\s", first, maxsplit=1)[0][:ERROR_TEXT].rstrip(".")


def _last_text(result: dict[str, Any]) -> str:
    message = next((m for m in reversed(result.get("messages") or []) if isinstance(m, AIMessage)), None)
    return message.text.strip() if message is not None else ""


async def _titles(org_id: int, ids: list[int]) -> tuple[dict[str, str], set[str]]:
    """The org's own files' titles, and which are only a saved link; another org's file stays unnamed."""
    if not ids:
        return {}, set()
    async with get_pool().connection() as conn:
        rows = await (await conn.execute(
            "SELECT id, title, COALESCE(storage_path, '') = '' AS link FROM documents"
            " WHERE id = ANY(%s) AND org_id = %s", (ids, org_id)
        )).fetchall()
    return {str(r["id"]): r["title"] or "Untitled file" for r in rows}, {str(r["id"]) for r in rows if r["link"]}


async def _mark(proposal_id: int, changes: dict[str, dict[str, Any]], by: dict[str, Any], reason: str) -> None:
    def change(work: dict, title: str) -> work_rules.Applied:
        return work_rules.apply(work, changes, by=by, via="agent",
                                reason=reason, title=title)

    await repo.save(get_pool(), proposal_id, change)


async def read(p: context.Current, public: bool = False, ask: dict[str, Any] | None = None) -> str:
    """Run every pending reader at once and record each one's outcome; returns what happened, file by file."""
    if public and BUILT.public is None:
        return "Public research is not available: no search key is configured. Say so in one line."
    try:
        run = await _claimed(p, public, ask)
    except Busy as busy:
        return f"REFUSED: {busy}."
    except _NothingToRead:
        return "Every ticked file has been read. Tick another file in step 2 to read more."
    return await run


async def search(p: context.Current) -> None:
    """The card's button: public research claimed now and run past the request, so neither the chat's choice
    to retry nor its stream ending can stop it. Raises Busy, or LookupError without a search key."""
    if BUILT.public is None:
        raise LookupError("Public research is not available: no search key is configured.")
    task = asyncio.create_task(await _claimed(p, True, None))
    _SEARCHES.add(task)  # held, or the loop may collect a task nothing else refers to
    task.add_done_callback(_SEARCHES.discard)


_SEARCHES: set[asyncio.Task[str]] = set()


async def _claimed(p: context.Current, public: bool, ask: dict[str, Any] | None) -> Coroutine[Any, Any, str]:
    """Mark the pending readers running under the row lock, and return the run that reads them."""
    pool = get_pool()
    by = await repo.user_name(pool, p.scope.user_id)
    files, links = await _titles(p.org_id, p.work.get("sources") or [])
    titles = {**files, FUNDER: f"what {p.funder_name} looks for", PUBLIC: "Public research on the problem and place"}
    keys: list[str] = []
    asked: list[str] = []  # the research ask's id, allocated inside the row lock
    await repo.save(pool, p.id, lambda work, title: _claim(work, title, keys, titles, by, public,
                                                            ask if public else None, asked))
    gate = asyncio.Semaphore(BUILT.parallel)
    ask_id = asked[0] if asked else None

    async def run() -> str:
        results = await asyncio.gather(*(_one(p, k, titles.get(k, "a file"), gate, by, k in links,
                                              (ask_id, ask) if k == PUBLIC and ask_id else None) for k in keys))
        return "\n".join(results)

    return run()


def _claim(work: dict, title: str, keys: list[str], titles: dict[str, str], by: dict[str, Any],
           public: bool = False, ask: dict[str, Any] | None = None, asked: list[str] | None = None,
           ) -> work_rules.Applied:
    """Inside the row lock: two people pressing at once get one run and one refusal."""
    keys.extend(pending(work, public=public))
    if not keys:
        raise _NothingToRead
    at = datetime.now(UTC).isoformat()
    running: dict[str, Any] = {f"readers.{k}": {"status": "running", "at": at, "by": by, "title": titles.get(k, "a file")}
                               for k in keys}
    if ask is not None and asked is not None:
        asked.append(research.next_ask_id(work))
        running[f"research_asks.{asked[0]}"] = {**ask, "status": "running", "at": at, "by": by}
    return work_rules.apply(work, running, by=by, via="agent", reason="reading the files", title=title)


async def _one(p: context.Current, key: str, title: str, gate: asyncio.Semaphore, by: dict[str, Any],
               link: bool = False, ask: tuple[str, dict[str, Any]] | None = None) -> str:
    """One reader, with its own sources: the contextvar is set inside the task, so no two readers share one."""
    if link:
        error = "it is a link to a web page, not a stored file; upload the file to read it"
        failed = {"status": "failed", "at": datetime.now(UTC).isoformat(), "by": by, "title": title, "error": error}
        await _mark(p.id, {f"readers.{key}": failed}, by, "could not read it")
        return f"{title}: could not read it ({error})."
    graph = {FUNDER: BUILT.funder, PUBLIC: BUILT.public}.get(key, BUILT.evidence)
    async with gate:
        token = run_sources.CURRENT.set(sources_for(p, key))
        run = PublicRun(avoid=(p.org_name,), ask=ask[0] if ask else None) if key == PUBLIC else None
        public = PUBLIC_RUN.set(run)
        # A run of its own: inheriting the chat's run would stream every reader's steps into the person's chat.
        var_child_runnable_config.set(None)
        written: str | None | BaseException = None
        try:
            inputs = await _public_inputs(p) if key == PUBLIC else None
            focus = ask[1] if ask else None
            task = public_task(p, *inputs, ask=focus) if inputs is not None else _task(p, key, title)
            if run is not None:
                run.task = task
                run.report = lambda: _progress(p.id, run, by)
            writing = brief.write(brief_task(p, *inputs, ask=focus), BUILT.brief) if inputs is not None else _no_brief()
            with propagate_caller(BUILT.trace):
                result, written = await asyncio.gather(graph.ainvoke({"messages": [HumanMessage(task)]}, config=BUILT.trace),
                                                       writing, return_exceptions=True)
            if isinstance(result, BaseException):
                raise result
            text = _last_text(result)
            error = _reason(text) if text.startswith(UNREADABLE) else None
            is_form = key.isdigit() and error is not None and error.startswith(FORM)
            if is_form:
                error = error.removeprefix(FORM).lstrip(" —–-:")
        except Exception as exc:  # noqa: BLE001 - one file's failure never stops the others
            logger.warning("proposal reader %s failed (%s)", key, type(exc).__name__)
            text, error, is_form = "", "something went wrong while reading it", False
        finally:
            PUBLIC_RUN.reset(public)
            run_sources.CURRENT.reset(token)
    outcome = {"status": "failed" if error else "done", "at": datetime.now(UTC).isoformat(), "by": by, "title": title,
               **({"error": error} if error else {}), **({"looks_like_form": True} if is_form else {}),
               **({"unopened": sorted(run.unopened)} if run else {}),
               **({"slices": run.slices} if run and run.slices else {})}
    marks: dict[str, dict[str, Any]] = {f"readers.{key}": outcome}
    added = 0
    if run is not None and not error:
        added = await _added(p.id, ask[0]) if ask else 0
        if isinstance(written, str):
            outcome["brief"] = written
    if ask is not None:
        marks[f"research_asks.{ask[0]}"] = {**ask[1], "status": outcome["status"], "at": outcome["at"], "by": by,
                                            **({} if error else {"added": added})}
    await _mark(p.id, marks, by, "could not read it" if error else "read it")
    if error:
        return f"{title}: could not read it ({error})."
    shown = f"\n\nThe brief now on the Secondary research card:\n{outcome['brief']}" if outcome.get("brief") else ""
    return f"{title}: read.\n{text}{shown}"


async def _progress(proposal_id: int, run: PublicRun, by: dict[str, Any]) -> None:
    """Each researcher's line on the card, written onto the running mark; a finished or deleted run is left alone."""
    def change(work: dict, title: str) -> work_rules.Applied:
        held = (work.get("readers") or {}).get(PUBLIC) or {}
        if held.get("status") != "running":
            raise _NotRunning
        return work_rules.apply(work, {f"readers.{PUBLIC}": {**held, "slices": [dict(s) for s in run.slices]}},
                                by=by, via="agent", reason="researching", title=title)

    try:
        await repo.save(get_pool(), proposal_id, change)
    except _NotRunning:
        pass


class _NotRunning(Exception):
    pass


async def _added(proposal_id: int, ask_id: str) -> int:
    """How many facts the run added for its ask, read after it; a failure counts none."""
    try:
        row = await repo.load(get_pool(), proposal_id)
    except Exception as exc:  # noqa: BLE001 - the search itself succeeded
        logger.warning(f"[_added] counting the ask's facts failed ({type(exc).__name__})")
        return 0
    return sum(1 for f in (((row or {}).get("work") or {}).get("facts") or {}).values() if f.get("ask") == ask_id)


class _NothingToRead(Exception):
    pass

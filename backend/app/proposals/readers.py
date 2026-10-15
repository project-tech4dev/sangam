"""The readers Sangam Pitch runs from step 2: one per ticked file, and one for the funder's side, in parallel.

Code launches them, not the model: which files are pending, the one lock on reading, and each file's status in
`work.readers` are decided here, so "Try again" re-reads only what failed.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.state import StateBackend
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables.config import var_child_runnable_config

from app.agent.harness import filesystem as filesystem_tools
from app.agent.models import resolve_model
from app.core.config import Settings
from app.db.pool import get_pool
from app.ingest import run_sources
from app.ingest.middleware import RunSources, fallback
from app.integrations.tracing import trace_config
from app.proposals import context, steps
from app.proposals import work as work_rules
from app.repositories import proposals as repo

logger = logging.getLogger(__name__)

FUNDER = "funder"  # work.readers' key for the funder's side; a file's key is its document id
UNREADABLE = "UNREADABLE:"  # a reader's last message starts with this when the file had nothing to read
ERROR_TEXT = 160
_PROMPTS = Path(__file__).parent / "prompts"


@dataclass
class _Built:
    evidence: Any = None
    funder: Any = None
    parallel: int = 1
    trace: dict[str, Any] | None = None


BUILT = _Built()


def build(settings: Settings, evidence_tools: list[Any], funder_tools: list[Any]) -> None:
    """Both readers, built once with the proposal agent. Neither has a web tool, nor a checkpoint of its own."""
    backend = StateBackend()
    research = resolve_model(settings.research_model)

    def reader(tools: list[Any], prompt: str) -> Any:
        return create_deep_agent(
            model=research,
            tools=tools,
            backend=backend,
            middleware=[
                filesystem_tools(backend, evict=False),
                RunSources(),
                *fallback(settings.research_model, settings.model),
            ],
            system_prompt=(_PROMPTS / prompt).read_text(encoding="utf-8"),
            checkpointer=False,
        ).with_config({"recursion_limit": settings.recursion_limit})

    BUILT.evidence = reader(evidence_tools, "evidence_reader.md")
    BUILT.funder = reader(funder_tools, "funder_file_reader.md")
    BUILT.parallel = max(1, settings.max_parallel_research)
    BUILT.trace = trace_config(settings, name="sangam_proposal_reader", tags=("proposal", "reader"))


class Busy(Exception):
    """Someone's readers are still running: the one lock in the feature, on reading only."""

    def __init__(self, reader: dict[str, Any], now: datetime):
        started = datetime.fromisoformat(str(reader["at"]))
        minutes = max(0, int((now - started).total_seconds() // 60))
        who = (reader.get("by") or {}).get("name") or "A teammate"
        super().__init__(f"{who} started reading the files {minutes} min ago; wait until they are read")


def pending(work: dict[str, Any], now: datetime | None = None) -> list[str]:
    """The readers to run: every ticked file and the funder's side not yet read, or failed. Raises Busy."""
    now = now or datetime.now(UTC)
    held = work.get("readers") or {}
    busy = [r for r in held.values() if r.get("status") == "running" and not steps.readers_stale(r, now)]
    if busy:
        raise Busy(busy[0], now)
    keys = [*(str(d) for d in work.get("sources") or []), FUNDER]
    return [k for k in keys if (held.get(k) or {}).get("status") != "done"]


def sources_for(p: context.Current, key: str) -> run_sources.Sources:
    """A file's reader may open that one file; the funder's reader, none of the org's."""
    if key == FUNDER:
        return run_sources.Sources(web=False)
    return run_sources.Sources(web=False, vault_org=p.org_id, vault_docs=frozenset({int(key)}))


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
        return work_rules.apply(work, {f"readers.{k}": v for k, v in changes.items()}, by=by, via="agent",
                                reason=reason, title=title)

    await repo.save(get_pool(), proposal_id, change)


async def read(p: context.Current) -> str:
    """Run every pending reader at once and record each one's outcome; returns what happened, file by file."""
    pool = get_pool()
    by = await repo.user_name(pool, p.scope.user_id)
    files, links = await _titles(p.org_id, p.work.get("sources") or [])
    titles = {**files, FUNDER: f"what {p.funder_name} looks for"}
    keys: list[str] = []
    try:
        await repo.save(pool, p.id, lambda work, title: _claim(work, title, keys, titles, by))
    except Busy as busy:
        return f"REFUSED: {busy}."
    except _NothingToRead:
        return "Every ticked file has been read. Tick another file in step 2 to read more."

    gate = asyncio.Semaphore(BUILT.parallel)
    results = await asyncio.gather(*(_one(p, k, titles.get(k, "a file"), gate, by, k in links) for k in keys))
    return "\n".join(results)


def _claim(work: dict, title: str, keys: list[str], titles: dict[str, str], by: dict[str, Any]) -> work_rules.Applied:
    """Inside the row lock: two people pressing at once get one run and one refusal."""
    keys.extend(pending(work))
    if not keys:
        raise _NothingToRead
    at = datetime.now(UTC).isoformat()
    running = {f"readers.{k}": {"status": "running", "at": at, "by": by, "title": titles.get(k, "a file")}
               for k in keys}
    return work_rules.apply(work, running, by=by, via="agent", reason="reading the files", title=title)


async def _one(p: context.Current, key: str, title: str, gate: asyncio.Semaphore, by: dict[str, Any],
               link: bool = False) -> str:
    """One reader, with its own sources: the contextvar is set inside the task, so no two readers share one."""
    if link:
        error = "it is a link to a web page, not a stored file; upload the file to read it"
        failed = {"status": "failed", "at": datetime.now(UTC).isoformat(), "by": by, "title": title, "error": error}
        await _mark(p.id, {key: failed}, by, "could not read it")
        return f"{title}: could not read it ({error})."
    graph = BUILT.funder if key == FUNDER else BUILT.evidence
    async with gate:
        token = run_sources.CURRENT.set(sources_for(p, key))
        # A run of its own: inheriting the chat's run would stream every reader's steps into the person's chat.
        var_child_runnable_config.set(None)
        try:
            result = await graph.ainvoke({"messages": [HumanMessage(_task(p, key, title))]}, config=BUILT.trace)
            text = _last_text(result)
            error = _reason(text) if text.startswith(UNREADABLE) else None
        except Exception as exc:  # noqa: BLE001 - one file's failure never stops the others
            logger.warning("proposal reader %s failed (%s)", key, type(exc).__name__)
            text, error = "", "something went wrong while reading it"
        finally:
            run_sources.CURRENT.reset(token)
    outcome = {"status": "failed" if error else "done", "at": datetime.now(UTC).isoformat(), "by": by, "title": title,
               **({"error": error} if error else {})}
    await _mark(p.id, {key: outcome}, by, "could not read it" if error else "read it")
    return f"{title}: could not read it ({error})." if error else f"{title}: read.\n{text}"


class _NothingToRead(Exception):
    pass

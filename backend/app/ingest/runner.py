"""Fan out over sources, write what is safe to write, and report everything."""

from __future__ import annotations

import asyncio
import collections
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.db.pool import get_pool
from app.ingest import writer
from app.ingest.adapters import india_csr
from app.ingest.adapters._http import SourceUnavailable
from app.ingest.extractor import extract_csr_years
from app.ingest.matcher import Match, resolve_funder
from app.ingest.records import FunderCsrYearRecord, FunderRecord
from app.ingest.sources import SOURCES, Source, resolve

logger = logging.getLogger(__name__)

# Each task holds an HTTP request and a pooled connection, and the pool is shared
# with the LangGraph checkpointer, which writes on every step — so this tracks the
# pool size rather than restating a number that would go stale beside it.
def max_concurrent_sources() -> int:
    return get_settings().db_gate_slots


@dataclass(slots=True)
class SourceOutcome:
    key: str
    status: str
    reason: str | None = None
    counts: dict[str, int] | None = None


async def catalog_baseline() -> dict[str, int]:
    """What the catalog holds now, so a run can be compared against it afterwards."""
    pool = get_pool()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT (SELECT count(*) FROM funders) AS funders, "
                "(SELECT count(*) FROM funder_csr_years) AS funder_csr_years, "
                "(SELECT count(*) FROM funder_activity) AS funder_activity, "
                "(SELECT count(*) FROM funder_locations) AS funder_locations, "
                "(SELECT count(*) FROM programs) AS programs, "
                "(SELECT count(*) FROM metrics) AS metrics, "
                "(SELECT count(*) FROM contacts) AS contacts, "
                "(SELECT count(*) FROM news_stories) AS news_stories, "
                "(SELECT count(*) FROM documents) AS documents, "
                "(SELECT count(*) FROM resolution_queue WHERE status = 'pending') AS pending_review"
            )
        ).fetchone()
    return dict(row)


async def run_import(
    source_keys: list[str] | None = None,
    *,
    goal: str,
    funders: list[str] | None = None,
    years: list[str] | None = None,
    model: Any = None,
    limit: int = 10,
    started_by: str | None = None,
) -> dict[str, Any]:
    """Run one import. Returns the same summary shape `summarise()` returns later."""
    requested, unknown = resolve(source_keys)
    pool = get_pool()

    async with pool.connection() as conn, conn.transaction():
        row = await (
            await conn.execute(
                "INSERT INTO ingest_runs (requested_sources, subjects, fiscal_years, "
                "started_by, notes) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (source_keys or [], funders or [], years or [], started_by, goal),
            )
        ).fetchone()
        run_id = row["id"]
        for name in unknown:
            await _item(conn, run_id, name, "source", "refused",
                        reason=f"No source named {name!r} is registered.")
        # One row for the whole held set, not one per source. At 74 registered
        # sources a per-source row meant ~50 inserts per default run, all saying
        # what the registry already says. summarise() re-derives the detail.
        held = [s for s in requested if not s.dispatchable]
        if held:
            by_rule = collections.Counter(s.access_rule.value for s in held)
            await _item(
                conn, run_id, "-", "run_scope", "refused",
                subject=f"{len(held)} sources held by their access rule",
                reason="; ".join(f"{rule}: {n}" for rule, n in sorted(by_rule.items())),
            )

    if parked := [s.key for s in requested if s.key in PARKED]:
        async with pool.connection() as conn, conn.transaction():
            for key in parked:
                await _refuse_parked(conn, run_id, key)

    gate = asyncio.Semaphore(max_concurrent_sources())
    runnable = [s for s in requested if s.dispatchable and s.key in ADAPTERS]
    # One task per source, or per (source, funder) pair when names are given, all
    # started together. The semaphore bounds them: each task holds a pooled
    # connection, and the pool is shared with the LangGraph checkpointer.
    tasks = [
        _run_source(src, run_id, model=model, limit=limit, gate=gate, subject=name, fiscal_year=year)
        for src in runnable
        for name in (funders or [None])
        for year in (years or [None])
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException as exc:
        # A stopped turn cancels this task; without the row update it would read 'running' forever.
        note = "cancelled" if isinstance(exc, asyncio.CancelledError) else f"{type(exc).__name__}: {exc}"
        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                "UPDATE ingest_runs SET finished_at = now(), status = 'failed', notes = %s WHERE id = %s",
                (note, run_id),
            )
        raise

    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            "UPDATE ingest_runs SET finished_at = now(), status = 'finished' WHERE id = %s", (run_id,)
        )
    return await summarise(run_id)


async def _run_source(
    src: Source, run_id: int, *, model: Any, limit: int, gate: asyncio.Semaphore,
    subject: str | None = None, fiscal_year: str | None = None,
):
    async with gate:
        pool = get_pool()
        label = " ".join(x for x in (src.name, subject and f"for {subject!r}", fiscal_year) if x)
        try:
            async with pool.connection() as conn:
                await ADAPTERS[src.key](
                    conn, run_id, model=model, limit=limit, subject=subject, fiscal_year=fiscal_year
                )
        except SourceUnavailable as exc:
            await _fail(run_id, src, str(exc), label=label)
        except Exception as exc:
            logger.exception("source %s failed for %s", src.key, subject)
            await _fail(run_id, src, f"{type(exc).__name__}: {exc}", label=label)


async def _fail(run_id: int, src: Source, reason: str, *, label: str | None = None) -> None:
    pool = get_pool()
    async with pool.connection() as conn, conn.transaction():
        await _item(conn, run_id, src.key, "source", "failed", reason=reason,
                    subject=label or src.name)


async def _ingest_india_csr(
    conn: Any, run_id: int, *, model: Any, limit: int, subject: str | None = None,
    fiscal_year: str | None = None,
) -> None:
    # Subject and year only aim the SEARCH. Whatever years the article turns out
    # to state are all extracted and written — narrowing the search is not a
    # reason to throw away a figure for a neighbouring year.
    items = await india_csr.fetch(_query(subject, fiscal_year), limit=limit)
    if model is None:
        raise SourceUnavailable("no model configured for extraction; set MODEL or pass one in")
    for item in items:
        records = await extract_csr_years(model, item)
        if not records:
            continue
        for rec in records:
            async with conn.transaction():
                await _write_csr_year(conn, run_id, rec)


async def _write_csr_year(conn: Any, run_id: int, rec: FunderCsrYearRecord) -> None:
    match = await resolve_funder(conn, rec.funder_name)

    # A name nothing resembles is a NEW funder, and new is the point of an
    # importer. Only a near-miss waits for a person: that is the case where
    # writing would silently merge two different organisations.
    if match.method == "none":
        funder = FunderRecord(
            name=rec.funder_name, source_url=rec.source_url, source_name=rec.source_name,
            fetched_at=rec.fetched_at, as_of=rec.as_of,
        )
        status, funder_id, changes = await writer.write_funder(conn, funder, match)
        await _item(
            conn, run_id, "india_csr", "funder", status, subject=rec.funder_name,
            target_table="funders", target_id=str(funder_id), changes=changes,
            match_method="none", source_url=rec.source_url,
        )
        match = Match("exact", funder_id)

    if not match.resolved:
        queue_id = await writer.queue_resolution(
            conn, raw_name=rec.funder_name, kind="funder", match=match, source="india_csr", rec=rec
        )
        await _item(
            conn, run_id, "india_csr", "funder_csr_year", "queued", subject=rec.funder_name,
            reason=_queue_reason(match), match_method=match.method, match_score=match.score,
            target_table="resolution_queue", target_id=str(queue_id), source_url=rec.source_url,
        )
        return
    document_id, _ = await writer.ensure_document(
        conn, rec, owner=writer.Owner.funder(match.entity_id), doc_type="news_article"
    )
    status, changes = await writer.write_csr_year(conn, rec, match.entity_id, document_id)
    await _item(
        conn, run_id, "india_csr", "funder_csr_year", status, subject=rec.funder_name,
        target_table="funder_csr_years", target_id=f"{match.entity_id}:{rec.fiscal_year}",
        changes=changes, match_method=match.method, match_score=match.score,
        source_url=rec.source_url, document_id=document_id,
    )


def _queue_reason(match: Any) -> str:
    if match.method == "trigram":
        names = ", ".join(f"{c['name']} ({c['score']})" for c in match.candidates)
        return f"Name is close to but not identical to: {names}. A person confirms before it is merged."
    return "No funder in the catalog matches this name, and nothing is close enough to propose."


# The sources this runner can actually fetch. A source may be legally readable
# and still not be here: registering a source makes it visible and reportable,
# writing an adapter is what makes it pull.
ADAPTERS: dict[str, Any] = {}
# Every source a run can actually pull, whatever runs it: the adapter table, or the news pipeline for tavily_news.
RUNNABLE: frozenset[str] = frozenset(ADAPTERS) | {"tavily_news"}


def runnable_for(keys: list[str] | None) -> frozenset[str]:
    """What a run may pull: no source named means the adapters only; a news pull costs money, so it must be named."""
    return RUNNABLE if keys else frozenset(ADAPTERS)
# Media & Signals parks both (spec D16): the adapters stay, nothing calls them. GDELT wrote news_mentions, now
# dropped; India CSR created funders from headlines. News now runs through app.ingest.news.pipeline.
PARKED: dict[str, str] = {
    "gdelt": "parked: news now comes through tavily_news; reviving it means writing news_links, not news_mentions",
    "india_csr": "parked: it created funders from headlines; CSR figures come from Import's funder research",
}


async def _refuse_parked(conn: Any, run_id: int, key: str) -> None:
    """A parked source asked for by name is a refused row with its reason, never a silence."""
    await _item(conn, run_id, key, "source", "refused", reason=PARKED[key])


def _query(subject: str | None, fiscal_year: str | None) -> str:
    """Aim the search. 'FY2023-24' reads as '2023-24' in an article's own words."""
    parts = [subject, "CSR", fiscal_year.removeprefix("FY") if fiscal_year else None]
    narrowed = " ".join(p for p in parts if p)
    return narrowed if subject else india_csr.DEFAULT_QUERY


async def _item(
    conn: Any, run_id: int, source: str, kind: str, status: str, *, reason: str | None = None,
    subject: str | None = None, target_table: str | None = None, target_id: str | None = None,
    changes: dict | None = None, match_method: str | None = None, match_score: float | None = None,
    source_url: str | None = None, document_id: int | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO ingest_run_items (run_id, source, record_kind, status, reason, subject, "
        "target_table, target_id, changes, match_method, match_score, source_url, document_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)",
        (run_id, source, kind, status, reason, subject, target_table, target_id,
         json.dumps(changes or {}, default=str), match_method, match_score, source_url, document_id),
    )


async def summarise(run_id: int) -> dict[str, Any]:
    """The run report, read back from the two tables rather than held in memory."""
    pool = get_pool()
    async with pool.connection() as conn:
        run = await (
            await conn.execute(
                "SELECT id, started_at, finished_at, status, requested_sources, subjects, "
                "fiscal_years, notes "
                "FROM ingest_runs WHERE id = %s",
                (run_id,),
            )
        ).fetchone()
        if run is None:
            return {"error": f"no import run with id {run_id}"}
        rows = await (
            await conn.execute(
                "SELECT source, status, count(*) AS n FROM ingest_run_items WHERE run_id = %s "
                "GROUP BY 1, 2 ORDER BY 1, 2",
                (run_id,),
            )
        ).fetchall()
        problems = await (
            await conn.execute(
                "SELECT source, record_kind, status, subject, reason FROM ingest_run_items "
                "WHERE run_id = %s AND status IN ('queued', 'failed', 'refused') ORDER BY status, source",
                (run_id,),
            )
        ).fetchall()
        written = await (
            await conn.execute(
                "SELECT source, record_kind, status, subject, target_table, changes FROM ingest_run_items "
                "WHERE run_id = %s AND status IN ('added', 'updated') ORDER BY source",
                (run_id,),
            )
        ).fetchall()

    per_source: dict[str, dict[str, int]] = {}
    for r in rows:
        per_source.setdefault(r["source"], {})[r["status"]] = r["n"]

    # A source that ran and found nothing has no rows at all, which would make it
    # look like it never ran. Seed those keys with zero counts, so "read nothing
    # new" and "was not read" stay different statements.
    requested = list(run["requested_sources"]) or [s.key for s in SOURCES.values()]
    permitted = {k for k in requested if k in SOURCES and SOURCES[k].dispatchable}
    # Permitted but unimplemented is not a failure. Reporting it as one would
    # tell the user that 21 sources are broken when they are simply not built.
    attempted = {k for k in permitted if k in runnable_for(list(run["requested_sources"]))}
    no_adapter = sorted(permitted - attempted)
    held = sorted(k for k in requested if k in SOURCES and not SOURCES[k].dispatchable)
    for key in attempted:
        per_source.setdefault(key, {})
    totals: dict[str, int] = {}
    for counts in per_source.values():
        for status, n in counts.items():
            totals[status] = totals.get(status, 0) + n

    finished = run["finished_at"] or datetime.now(UTC)
    return {
        "run_id": run["id"],
        "subjects": list(run["subjects"]),
        "fiscal_years": list(run["fiscal_years"]),
        "goal": run["notes"],
        "status": run["status"],
        "started_at": run["started_at"].isoformat(),
        "duration_seconds": round((finished - run["started_at"]).total_seconds(), 1),
        "sources_processed": sorted(k for k in attempted if "failed" not in per_source.get(k, {})),
        "sources_refused": held,
        "sources_without_adapter": no_adapter,
        "sources_failed": sorted(k for k, v in per_source.items() if "failed" in v),
        "totals": totals,
        "by_source": per_source,
        "written": [dict(r) for r in written],
        "needs_attention": [dict(r) for r in problems],
    }

"""The importer's tools. Like every Sangam tool, they return errors, never raise."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from app.agent.models import resolve_model
from app.core.config import get_settings
from app.db.pool import get_pool
from app.ingest.runner import run_import, summarise
from app.ingest.sources import SOURCES

logger = logging.getLogger(__name__)


@tool
async def list_import_sources() -> str:
    """List every registered data source, its access rule, and why that rule applies.

    Use this before running an import, and whenever the user asks why a source was
    skipped. A source is only crawled when its rule is open_api or crawl_allowed;
    every other rule means a person must enter the data by hand or someone must get
    permission first. The basis is the evidence for the rule — quote it to the user.
    """
    try:
        lines = []
        for s in SOURCES.values():
            mark = "RUNS" if s.dispatchable else "HELD"
            checked = s.robots_checked_at.isoformat() if s.robots_checked_at else "not checked"
            lines.append(
                f"[{mark}] {s.key} — {s.name} ({s.host})\n"
                f"  rule: {s.access_rule.value} (checked {checked})\n"
                f"  basis: {s.basis}\n"
                f"  yields: {', '.join(s.yields)}"
            )
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"list_import_sources failed: {exc}"


@tool
async def run_import_now(sources: str = "", limit: int = 10) -> str:
    """Run an import and return the full summary. This WRITES to the database.

    Args:
        sources: comma-separated source keys (e.g. "india_csr,gdelt"). Empty means
            every registered source — the ones that may not be crawled are reported
            as refused rather than skipped silently.
        limit: how many items to pull per source. Keep it small (5-20); each item
            costs a model call for extraction.

    New funders are added. Names that closely resemble an existing funder are NOT
    merged — they go to the review queue, because merging two different organisations
    is the one mistake this pipeline cannot undo. Report the queue to the user.
    """
    try:
        settings = get_settings()
        keys = [s.strip() for s in sources.split(",") if s.strip()] or None
        summary = await run_import(keys, model=resolve_model(settings.model), limit=limit)
        return format_summary(summary)
    except Exception as exc:
        logger.exception("run_import_now failed")
        return f"run_import_now failed: {type(exc).__name__}: {exc}"


@tool
async def import_run_summary(run_id: int = 0) -> str:
    """Re-read the summary of an import run. 0 means the most recent run.

    The summary is built from the run tables, so it says the same thing now as it
    did when the run finished.
    """
    try:
        if run_id <= 0:
            pool = get_pool()
            async with pool.connection() as conn:
                row = await (
                    await conn.execute("SELECT id FROM ingest_runs ORDER BY id DESC LIMIT 1")
                ).fetchone()
            if row is None:
                return "No import has been run yet."
            run_id = row["id"]
        return format_summary(await summarise(run_id))
    except Exception as exc:  # noqa: BLE001
        return f"import_run_summary failed: {exc}"


@tool
async def pending_resolutions(limit: int = 20) -> str:
    """Names waiting for a person to confirm before anything is merged.

    Each row is a name from a source that resembled an existing funder without
    matching it. Show the candidates and their scores; do not guess on the user's
    behalf.
    """
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id, raw_name, entity_kind, source, candidates, source_url "
                    "FROM resolution_queue WHERE status = 'pending' ORDER BY created_at DESC LIMIT %s",
                    (min(limit, 100),),
                )
            ).fetchall()
        if not rows:
            return "Nothing is waiting for review."
        out = []
        for r in rows:
            cands = ", ".join(
                f"{c['name']} [funder:{c['id']}] ({c['score']})" for c in (r["candidates"] or [])
            ) or "no candidate above the threshold"
            out.append(f"#{r['id']} {r['raw_name']!r} from {r['source']} → {cands}\n  {r['source_url']}")
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"pending_resolutions failed: {exc}"


def format_summary(s: dict[str, Any]) -> str:
    """One shape for the run report, wherever it is read."""
    if "error" in s:
        return s["error"]
    t = s["totals"]
    head = (
        f"Import run #{s['run_id']} — {s['status']} in {s['duration_seconds']}s\n"
        f"  processed: {', '.join(s['sources_processed']) or 'none'}\n"
        f"  refused:   {', '.join(s['sources_refused']) or 'none'}\n"
        f"  failed:    {', '.join(s['sources_failed']) or 'none'}\n"
        f"  records:   {t.get('added', 0)} added, {t.get('updated', 0)} updated, "
        f"{t.get('matched', 0)} already current, {t.get('queued', 0)} queued for review"
    )
    parts = [head]
    empty = [k for k in s["sources_processed"] if not s["by_source"].get(k)]
    if empty:
        parts.append(
            f"\n{', '.join(empty)} ran and found nothing new. That is a result, not a failure."
        )
    if s["written"]:
        parts.append("\nWritten:")
        for w in s["written"]:
            changed = ", ".join(w["changes"]) if w["changes"] else ""
            parts.append(f"  {w['status']}: {w['subject']} → {w['target_table']} {changed}".rstrip())
    if s["needs_attention"]:
        parts.append("\nCould not be processed:")
        for p in s["needs_attention"]:
            parts.append(f"  {p['status']}: {p['subject'] or p['source']} — {p['reason']}")
    return "\n".join(parts)

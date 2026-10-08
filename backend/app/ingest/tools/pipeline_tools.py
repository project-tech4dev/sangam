"""The adapter path: the source registry, the runs that pull from it, and the staff workbooks.

One tool per step of a write-run — see which sources may be read, say what a
run would pull, run it, read the summary back, and see what it queued for a
person. Like every Sangam tool, they return errors, never raise."""

from __future__ import annotations

import collections
import logging
from typing import Any

from langchain_core.tools import tool

from app.agent.models import resolve_model
from app.core.config import get_settings
from app.db.pool import get_pool
from app.ingest import staff_sources
from app.ingest.runner import catalog_baseline, run_import, summarise
from app.ingest.sources import SOURCES, Category, resolve

logger = logging.getLogger(__name__)


@tool
async def list_import_sources(category: str = "", detail: str = "") -> str:
    """Summarise the source registry: how many sources there are, and their access rules.

    There are ~74 registered sources, so this returns COUNTS by default, not the
    whole list. Narrow it to get detail:

    Args:
        category: one of funder, ngo, rfp, media — restricts the summary to that
            category and lists the sources that can actually be read.
        detail: a source key, or a rule name like "no_scraping_manual_entry_allowed",
            to get full entries with the basis quoted. Use this when a user asks
            why a particular source was skipped, and quote the basis back to them.

    A source is only crawled when its rule is open_api or crawl_allowed. Every
    other rule means a person must enter the data by hand, or someone must get
    permission, buy a licence, or run an export from an Indian network first.
    """
    try:
        chosen = list(SOURCES.values())
        if category:
            try:
                wanted = Category(category.strip().lower())
            except ValueError:
                return f"Unknown category {category!r}. Use one of: {', '.join(c.value for c in Category)}."
            chosen = [s for s in chosen if wanted in s.categories]

        if detail:
            needle = detail.strip().lower()
            picked = [s for s in chosen if needle in (s.key, s.access_rule.value)]
            if not picked:
                return f"Nothing registered matches {detail!r}."
            return "\n".join(_full_entry(s) for s in picked)

        runs = [s for s in chosen if s.dispatchable and s.key in _adapter_keys()]
        permitted = [s for s in chosen if s.dispatchable and s.key not in _adapter_keys()]
        by_rule = collections.Counter(s.access_rule.value for s in chosen if not s.dispatchable)

        scope = f" in {category}" if category else ""
        lines = [f"{len(chosen)} sources registered{scope}."]
        lines.append(f"\nCan be read AND have an adapter ({len(runs)}) — these actually pull:")
        for s in runs:
            lines.append(f"  {s.key} ({s.host}) → {', '.join(s.yields)}")
        if permitted:
            lines.append(
                f"\nPermitted but no adapter yet ({len(permitted)}): "
                + ", ".join(s.key for s in permitted)
            )
        if by_rule:
            lines.append("\nHeld, by rule:")
            for rule, n in sorted(by_rule.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {rule}: {n}")
            lines.append(
                '\nAsk again with detail="<source key or rule>" for the evidence behind any of these.'
            )
        if not category:
            counts = ", ".join(
                f"{c.value} {len([s for s in SOURCES.values() if c in s.categories])}" for c in Category
            )
            lines.append(f"\nBy category: {counts}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"list_import_sources failed: {exc}"


def _adapter_keys() -> set[str]:
    from app.ingest.runner import ADAPTERS

    return set(ADAPTERS)


def _full_entry(s) -> str:
    mark = "RUNS" if s.dispatchable else "HELD"
    checked = s.robots_checked_at.isoformat() if s.robots_checked_at else "not checked"
    host = s.host or "a class of sites, checked per host"
    return (
        f"[{mark}] {s.key} — {s.name} ({host})\n"
        f"  rule: {s.access_rule.value} (checked {checked})\n"
        f"  basis: {s.basis}\n"
        f"  yields: {', '.join(s.yields)}"
    )


@tool
async def plan_import(funders: str = "", years: str = "", sources: str = "", limit: int = 10) -> str:
    """Say what a run WOULD pull, from where, and against what the catalog already holds.

    Read-only: this writes nothing. Call it before every run and show the user the
    plan, so the goal and the reach of the run are agreed before anything changes.

    Args:
        funders: comma-separated funder names the run would research.
        years: comma-separated fiscal years, e.g. "FY2023-24,FY2024-25".
        sources: comma-separated source keys, or empty for every registered source.
        limit: items per source the run would request.
    """
    try:
        keys = [s.strip() for s in sources.split(",") if s.strip()] or None
        names = [n.strip() for n in funders.split(",") if n.strip()]
        fys = [y.strip() for y in years.split(",") if y.strip()]
        requested, unknown = resolve(keys)
        baseline = await catalog_baseline()

        adapters = _adapter_keys()
        will_run = [s for s in requested if s.dispatchable and s.key in adapters]
        no_adapter = [s for s in requested if s.dispatchable and s.key not in adapters]
        held = [s for s in requested if not s.dispatchable]

        lines = ["PLAN — nothing is written by this step."]
        if names:
            searches = len(names) * len(will_run) * max(len(fys), 1)
            scope = f"{len(names)} name(s), concurrently: {', '.join(names)}"
            if fys:
                scope += f"\nAcross {len(fys)} year(s): {', '.join(fys)}"
            lines.append(
                f"\nResearching {scope}.\n"
                f"That is {searches} searches, each costing a model call per article read."
            )
        else:
            lines.append(
                "\nNo funder named, so this pulls whatever the sources published most recently. "
                "If the user asked about particular funders, pass their names instead."
            )
        lines += ["", "Will pull:"]
        if not will_run:
            lines.append("  nothing: no requested source both may be read and has an adapter.")
        for s in will_run:
            lines.append(
                f"  {s.key} ({s.host}) — up to {limit} items → {', '.join(s.yields)}\n"
                f"    permitted because: {s.basis}"
            )
        if no_adapter:
            lines += ["", f"Permitted, but nothing reads them yet ({len(no_adapter)}): "
                          + ", ".join(s.key for s in no_adapter)]
        # Counts, not entries: naming all ~50 held sources here would put the
        # whole registry into the prompt before every single run.
        if held:
            by_rule = collections.Counter(s.access_rule.value for s in held)
            lines += ["", f"Will NOT pull ({len(held)} held by their access rule):"]
            for rule, n in sorted(by_rule.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {rule}: {n}")
            lines.append('  Ask list_import_sources(detail="<key or rule>") for the evidence.')
        if unknown:
            lines += ["", f"Unknown source names, ignored: {', '.join(unknown)}"]

        lines += [
            "",
            "Catalog before the run:",
            "  " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in baseline.items()),
            "",
            (
                "New names are added. A name that resembles an existing funder without "
                "matching it is queued for a person, never merged."
            ),
        ]
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"plan_import failed: {exc}"


@tool
async def run_import_now(
    goal: str, funders: str = "", years: str = "", sources: str = "", limit: int = 10
) -> str:
    """Run an import and return the full summary. This WRITES to the database.

    Call plan_import first and show the user the plan. The goal is stored on the
    run, so months later the run says what it was for.

    Args:
        goal: one sentence on what this run is for, in the user's terms, e.g.
            "FY2025-26 CSR figures for Indian corporate funders". Required.
        funders: comma-separated funder names to research, e.g.
            "Axis Bank Foundation, SBI Foundation". Each name is searched in every
            runnable source, and the names run CONCURRENTLY. Leaving this empty
            asks a different question — "whatever these sources published most
            recently" — so when the user names funders, pass them.
        years: comma-separated fiscal years, "FY2023-24,FY2024-25,FY2025-26". Each
            year is searched separately, so three years of three funders is nine
            searches — say so before running it. Empty searches without a year,
            which in practice returns the most recent one. Years only aim the
            SEARCH: whatever years an article turns out to state are all written.
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
        if not goal.strip():
            return "run_import_now needs a goal: one sentence on what this run is for."
        names = [n.strip() for n in funders.split(",") if n.strip()] or None
        fys = [y.strip() for y in years.split(",") if y.strip()] or None
        summary = await run_import(
            keys, goal=goal.strip(), funders=names, years=fys,
            model=resolve_model(settings.utility_model or settings.model), limit=limit,
        )
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
        f"  goal:      {s.get('goal') or 'not recorded'}\n"
        f"  names:     {', '.join(s.get('subjects') or []) or 'none — latest from each source'}\n"
        f"  years:     {', '.join(s.get('fiscal_years') or []) or 'not narrowed by year'}\n"
        f"  processed: {', '.join(s['sources_processed']) or 'none'}\n"
        # A count, not 51 keys: the rules behind them are listed below.
        f"  refused:   {len(s['sources_refused'])} held by their access rule\n"
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
    if s.get("sources_without_adapter"):
        names = ", ".join(s["sources_without_adapter"])
        parts.append(
            f"\nPermitted but not built yet ({len(s['sources_without_adapter'])}): {names}. "
            f"These are legally readable; nothing reads them."
        )
    if s["needs_attention"]:
        parts.append("\nCould not be processed:")
        # Bounded: at 74 registered sources the held set alone was ~50 lines.
        for p in s["needs_attention"][:15]:
            parts.append(f"  {p['status']}: {p['subject'] or p['source']} — {p['reason']}")
        if len(s["needs_attention"]) > 15:
            parts.append(f"  … and {len(s['needs_attention']) - 15} more; ask for the run detail.")
    return "\n".join(parts)


@tool
async def read_source_rows(name: str, sheet: str = "") -> str:
    """Read the staff-only workbooks — statutory CSR filing exports and the CSO funder workbook — for one name.

    Searches every sheet of every uploaded workbook for rows naming `name`, or any name
    the catalog holds for that funder (its aliases). Returns each sheet's header rows, the
    matching rows, and the section heading and sub-table header above each match, every
    row as cell=value pairs with a [source:<document>#<sheet>!<cell>] marker.

    Cite a fact by the marker of the CELL that holds it (change the cell in the marker),
    with the dataset's source_url and source_name printed above its rows. The source_url
    is cited, never fetched. Amounts are as printed: save the figure with the sheet's
    unit (crore, lakh or a unit written in the cell), as "The staff sheets" in your
    instructions says.

    Contact columns are removed by design. The filer is often the parent company, not
    the foundation: search both names.

    Args:
        name: a company, funder or CSO name, at least three letters.
        sheet: optional part of a sheet name (e.g. "2023-24") to read one sheet only.
    """
    try:
        return await staff_sources.read_rows(get_pool(), name, sheet=sheet)
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure; type only, never a value
        return f"read_source_rows failed: {type(exc).__name__}"

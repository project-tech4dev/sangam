"""Saved research against the catalog: what a save would write, the review and coverage views, and the save itself.

The Import screen's routes and the `promote_research` tool both call `save_to_catalog`; nothing here is a tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from psycopg.errors import UniqueViolation

from app.agent.tools.sql.catalog import CATALOG
from app.core.security import CallerScope
from app.db.pool import get_pool
from app.ingest import brief, review, undo
from app.ingest.caller import scope, without_private
from app.ingest.promote import MERGEABLE, org_match, promote
from app.ingest.reading import vault as vault_store
from app.ingest.research import coverage
from app.ingest.research.expectations import CONCEPTS, concepts_for
from app.ingest.writer import UNWRITTEN, Gate, slugify

logger = logging.getLogger(__name__)

# kind -> (entity table, foreign key)
ENTITY_KEYS: dict[str, tuple[str, str]] = {"funder": ("funders", "funder_id"), "org": ("orgs", "org_id")}


async def held_per_concept(
    conn: Any, entity_id: int, entity_kind: str
) -> dict[str, tuple[int, list[str]]]:
    """Row counts, and the fiscal years already covered, per concept.

    Both halves have to move together. This used to walk every concept in the
    registry and emit `WHERE funder_id = %s`, which was fine while every table
    had one — the moment orgs tables joined the registry it became `SELECT …
    FROM orgs WHERE funder_id = %s`, an UndefinedColumn swallowed by the broad
    `except` in research_goals, **for funder runs too**, because the loop runs
    before anything is printed. So it iterates the concepts for this kind and
    takes the foreign key from the same place.
    """
    entity_table, fk = ENTITY_KEYS[entity_kind]
    out: dict[str, tuple[int, list[str]]] = {}
    for concept in concepts_for(entity_kind):
        spec = CONCEPTS[concept]
        table = spec.table
        # The entity's own row, which is the match we already have in hand.
        if table == entity_table:
            out[concept] = (1, [])
            continue
        has_year = any(c.name == "fiscal_year" for c in CATALOG[table].columns)
        years = ", array_agg(DISTINCT fiscal_year)" if has_year else ", '{}'::text[]"
        # funder_activity hangs off the funder; an NGO's lines are the ones naming it as the partner.
        col = "partner_org_id" if entity_kind == "org" and table == "funder_activity" else fk
        # Table, column and filter column come from module constants, never a caller.
        where, params = f"{col} = %s", [entity_id]
        if spec.row_filter:
            where += f" AND {spec.row_filter[0]} = %s"
            params.append(spec.row_filter[1])
        found = await (
            await conn.execute(
                f"SELECT count(*) AS n{years} AS years FROM {table} WHERE {where}", tuple(params)
            )
        ).fetchone()
        out[concept] = (found["n"], [y for y in (found["years"] or []) if y])
    return out


async def research_rows(
    pool: Any, slug: str, caller: CallerScope | None = None, *, vault: bool = False
) -> list[dict[str, Any]]:
    """The newest row per entity, its findings read from the brief; for a caller who is not staff, without private ones.

    `vault` adds Doc Vault findings: only for a writer or a person, never a context that briefs researchers."""
    caller = caller or scope()
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT DISTINCT ON (slug) * FROM entity_research "
                + ("WHERE slug = %s " if slug else "")
                + "ORDER BY slug, researched_at DESC",
                (slug,) if slug else (),
            )
        ).fetchall()
    # Vault findings live in vault_research alone: one in the shared row was never checked against a vault.
    out = [{**r, "findings": [f for f in r.get("findings") or [] if not vault_store.is_vault_url(f.get("source_url"))]}
           for r in (dict(r) if caller.is_staff else without_private(dict(r)) for r in rows)]
    # The brief is the record: promotion, its plan and coverage all read its facts, not one run's.
    async with pool.connection() as conn:
        out = [await brief.promotable(r, [_public_row(x, caller) for x in await brief.rows_for(conn, r["slug"])])
               for r in out]
    return [await _with_vault(pool, r, caller) for r in out] if vault else out


def _public_row(row: dict[str, Any], caller: CallerScope) -> dict[str, Any]:
    """An earlier run, without its Doc Vault findings and, for a caller who is not staff, its private ones."""
    row = dict(row) if caller.is_staff else without_private(dict(row))
    return {**row, "findings": [f for f in row.get("findings") or [] if not vault_store.is_vault_url(f.get("source_url"))]}


async def _with_vault(pool: Any, row: dict[str, Any], caller: CallerScope) -> dict[str, Any]:
    """The row plus the newest vault findings of each org whose files this caller may read."""
    slugs = sorted({row["slug"], slugify(row.get("entity_name") or row["slug"])})
    async with pool.connection() as conn:
        found = await (await conn.execute(
            "SELECT DISTINCT ON (v.org_id) v.org_id, v.findings, v.documents_read, "
            "(SELECT jsonb_object_agg(d.id, coalesce(d.title, 'untitled')) FROM documents d "
            " WHERE d.id = ANY(v.documents_read)) AS titles "
            "FROM vault_research v WHERE v.slug = ANY(%s) ORDER BY v.org_id, v.researched_at DESC",
            (slugs,),
        )).fetchall()
    readable = [v for v in found if caller.can_read_org(v["org_id"])]
    if not readable:
        return row
    return {**row, "findings": [*(row.get("findings") or []), *(f for v in readable for f in v["findings"])],
            "vault": [{"org_id": v["org_id"], "documents_read": list(v["documents_read"]),
                       "titles": dict(v.get("titles") or {})} for v in readable]}


async def write_preview(slug: str) -> dict[str, Any]:
    """What SaveQuestions puts on the pause: a funder's case 3 and 4 questions, the planned rows, and coverage."""
    rows = await research_rows(get_pool(), slug, vault=True)
    if not rows:
        return {"questions": [], "planned": [], "coverage": ""}
    row = rows[0]
    if row.get("entity_kind") == "org":
        head = coverage.render(coverage.compute(row)).split("\n")[1]
        return {"questions": [], "planned": ["An NGO: blanks are filled, conflicts are reported."], "coverage": head}
    async with get_pool().connection() as conn:
        plan = await promote(conn, row, gate=Gate(plan=True))
    counts: dict[str, int] = {}
    for item in plan.get("plan", {}).get("items", []):
        if item["case"] in (2, 5):
            counts[item["table"]] = counts.get(item["table"], 0) + 1
    planned = [f"{table}: {n} row(s)" for table, n in sorted(counts.items())]
    if plan.get("held"):
        planned.append(f"held back: {len(plan['held'])}")
    head = coverage.render(coverage.compute(row, report=plan)).split("\n")[1]
    return {"questions": plan.get("questions", []), "planned": planned, "coverage": head}


async def _rows_now(conn: Any, kind: str | None, entity_id: int | None) -> dict[str, int] | None:
    """Catalog rows per concept for one entity; None when there is no entity to count yet."""
    if kind not in ENTITY_KEYS or entity_id in (None, UNWRITTEN):
        return None
    return {c: n for c, (n, _) in (await held_per_concept(conn, entity_id, kind)).items()}


def saved_since_research(row: dict[str, Any]) -> bool:
    """Whether the row's save covers its findings: a same-day re-run rewrites the row after the save (#222)."""
    saved_at, researched_at = row.get("saved_at"), row.get("researched_at")
    return not (saved_at and researched_at and researched_at > saved_at)


async def _record_save(conn: Any, row: dict[str, Any], report: dict[str, Any]) -> None:
    """Keep what this save wrote on the research row. Afterwards a plan reads every row as `same`,
    so this is the only record of what the profile held before."""
    entity = report.get("entity")
    after = await _rows_now(conn, entity["kind"], entity["id"]) if entity else None
    saved = coverage.saved_record(row.get("saved"), report, after)
    if saved is None:
        if row.get("saved"):  # a re-run's save that changed nothing still saves the re-run
            await conn.execute("UPDATE entity_research SET saved_at = now() WHERE id = %s", (row["id"],))
        return
    await conn.execute(
        "UPDATE entity_research SET saved = %s::jsonb, saved_at = now() WHERE id = %s",
        (json.dumps(saved, default=str), row["id"]),
    )


async def coverage_view(slug: str, caller: CallerScope | None = None) -> dict[str, Any] | None:
    """Coverage per concept, with rows before and after: from the stored save, else a funder's dry run.
    An NGO not yet saved has no before/after: its write cannot be dry-run."""
    pool = get_pool()
    rows = await research_rows(pool, slug, caller, vault=True)
    if not rows:
        return None
    row = rows[0]
    kind = row.get("entity_kind")
    saved = row.get("saved") if saved_since_research(row) else None
    if saved and row.get("private_removed"):
        # Held lines quote the values they held, private ones included; the counts stay.
        saved = {**saved, "held": []}
    entity, reasons, held, questions = None, [], [], 0
    changes: dict[str, dict[str, int]] = {}
    before: dict[str, int] | None = None
    after: dict[str, int] | None = None
    report: dict[str, Any] | None = None
    if saved:
        stage = "saved"
        entity, reasons, held = saved.get("entity"), saved.get("reasons", []), saved.get("held", [])
        changes, before, after = saved.get("changes", {}), saved.get("rows_before"), saved.get("rows_after")
        report = {"skipped": saved.get("skipped", {}), "held": held}
    elif kind != "org":
        stage = "planned"
        async with pool.connection() as conn:
            report = await promote(conn, row, gate=Gate(plan=True))
            entity, reasons, held = report.get("entity"), report["reasons"], report["held"]
            questions = len(report.get("questions", []))
            # A dry run does not archive documents, so a plan's document count reads 0.
            changes = coverage.changes_by_concept(report)
            if entity:
                before = await _rows_now(conn, kind, entity["id"]) or {c: 0 for c in concepts_for(kind)}
                after = {c: n + changes.get(c, {}).get("added", 0) for c, n in before.items()}
        if entity and entity.get("id") == UNWRITTEN:
            entity = {**entity, "id": None}  # a funder the plan would add has no id to link to yet
    else:
        stage = "unsaved"
    return coverage.view(row, stage=stage, report=report, entity=entity, reasons=reasons, held=held,
                         questions=questions, changes=changes, before=before, after=after)


async def review_view(slug: str, caller: CallerScope | None = None) -> dict[str, Any] | None:
    """The review card's body: answers with their proof, what is missing, the questions, what saving adds."""
    pool = get_pool()
    rows = await research_rows(pool, slug, caller, vault=True)
    if not rows:
        return None
    row = rows[0]
    kind = row.get("entity_kind")
    questions: list[dict[str, Any]] = []
    saves: dict[str, dict[str, int]] = {}
    async with pool.connection() as conn:
        if kind == "funder":
            plan = await promote(conn, row, gate=Gate(plan=True))
            questions, saves = plan.get("questions", []), coverage.changes_by_concept(plan)
            existing = bool(plan.get("entity") and plan["entity"].get("id") not in (None, UNWRITTEN))
        else:
            # The same match saving would make: on an existing NGO a save only fills blanks.
            asking = Gate(plan=True)
            match = await org_match(conn, row, asking)
            questions = asking.asked()
            existing = bool(row.get("resolved_org_id")) or bool(match and match.method in MERGEABLE)
    return {
        "slug": row["slug"], "name": row.get("canonical_name") or row.get("entity_name") or row["slug"],
        "kind": kind, "existing": existing,
        "answers": review.answers(row), "missing": review.missing(row),
        "questions": [review.question(q) for q in questions],
        "saves": [{"concept": c, "topic": review.topic(c), **n} for c, n in saves.items()
                  if n.get("added") or n.get("updated")],
    }


async def _may_save(
    conn: Any, caller: CallerScope, row: dict[str, Any], decisions: dict[str, str] | None = None
) -> str | None:
    """Why this caller may not save this research to the catalog, or None."""
    name = row.get("canonical_name") or row.get("entity_name") or row["slug"]
    if row.get("entity_kind") != "org":
        return None if caller.can_save_funder() else "saving to Sangam needs a signed-in user."
    org_id = row.get("resolved_org_id")
    if org_id is None:
        # A steward who says a close name is their NGO saves to it, as staff would.
        match = await org_match(conn, row, Gate(decisions))
        org_id = match.entity_id if match and match.method in MERGEABLE else None
    if org_id is None:
        return f"{name} is not an NGO Sangam holds yet; the Sangam team adds new NGOs."
    if not caller.can_research_org(org_id):
        return f"{name} is an NGO; only its stewards and the Sangam team save research about it."
    return None


class SaveRefused(Exception):
    """This caller may not save this research; the message says why, in the person's words."""


async def save_to_catalog(slug: str, caller: CallerScope, decisions: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Write saved research into the catalog, one transaction and one undoable promotion per row.
    Raises LookupError with no research, SaveRefused when the caller's role may not save it."""
    if not slug and not caller.is_staff:
        raise SaveRefused("promote one researched organisation at a time: pass its slug.")
    pool = get_pool()
    rows = await research_rows(pool, slug, caller, vault=True)
    if not rows:
        raise LookupError(slug)
    async with pool.connection() as conn:
        refused = await _may_save(conn, caller, rows[0], decisions) if not caller.is_staff else None
    if refused:
        raise SaveRefused(refused)
    reports = []
    for row in rows:
        for attempt in range(2):
            try:
                async with pool.connection() as conn, conn.transaction():
                    promotion = await undo.start(conn, row.get("id"), row["slug"], caller.user_id)
                    report = await promote(conn, row, gate=Gate(decisions or {}))
                    await _record_save(conn, row, report)
                    report["promotion_id"] = promotion if await undo.finish(conn, promotion) else None
                break
            except UniqueViolation:
                # Another save added the same row between a look-up and its insert; the retry finds it.
                if attempt:
                    raise
        reports.append(report)
        await _publish_states(pool, row["slug"], report.get("facts") or {})
    return reports


async def _publish_states(pool: Any, slug: str, states: dict[str, dict[str, Any]]) -> None:
    """Write what the save did with each fact into the brief. The catalog is already committed, so a failure is logged."""
    try:
        async with pool.connection() as conn:
            rows = await brief.rows_for(conn, slug)
        if rows:
            await brief.publish(rows, states=states)
    except Exception:
        logger.exception("brief for %s: the save's states were not written back", slug)

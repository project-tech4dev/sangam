"""One claimed pool row: resolve it against Sangam's funders, else research it with Scout and leave it for review."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.ingest.catalog.matcher import resolve_funder
from app.ingest.catalog.writer_funder import cin_holder
from app.ingest.pool import queue
from app.ingest.runner import record_item

SOURCE = "funder_pool"

Research = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]

# Each slug's latest research, with the CIN its identity finding names.
IDENTITY_CIN = """
SELECT r.slug, r.entity_name, r.canonical_name, r.status, f->>'cin' AS cin
  FROM entity_research r LEFT JOIN LATERAL jsonb_array_elements(r.findings) f ON f->>'concept' = 'identity'
 WHERE r.slug = ANY(%s)
   AND r.researched_on = (SELECT max(researched_on) FROM entity_research WHERE slug = r.slug)
"""

# When Scout's change check finds nothing new it runs no researcher; the funder's earlier research stands.
EARLIER = """
SELECT slug FROM entity_research
 WHERE lower(entity_name) = lower(%(name)s) OR lower(canonical_name) = lower(%(name)s)
 ORDER BY researched_at DESC LIMIT 1
"""


def method(match_method: str) -> str:
    """ingest_run_items.match_method has no 'website'; a website match is an identifier match there."""
    return "identifier" if match_method == "website" else match_method


async def process(pool: Any, row: dict[str, Any], research: Research) -> tuple[str, str | None]:
    """(status, error) for one row; the row and its run are updated before this returns."""
    async with pool.connection() as conn:
        run_id = await queue.start_run(conn, row)
        website = (row["signals"] or {}).get("website")
        match = await resolve_funder(conn, row["name"], cin=row["cin"], website=website)
        if match.resolved:
            await record_item(conn, run_id, SOURCE, "funder", "matched", subject=row["name"], target_table="funders",
                              target_id=str(match.entity_id), match_method=method(match.method))
            await queue.finish(conn, row, "skipped", funder_id=match.entity_id)
            return "skipped", None
        prior = await (await conn.execute(
            "SELECT status, resolved_funder_id FROM resolution_queue "
            "WHERE entity_kind = 'funder' AND raw_name = %s AND source = %s", (row["name"], SOURCE))).fetchone()
        decided = prior["status"] if prior else "pending"
        if match.method == "trigram" and decided == "accepted" and prior["resolved_funder_id"]:
            await record_item(conn, run_id, SOURCE, "funder", "matched", subject=row["name"], target_table="funders",
                              target_id=str(prior["resolved_funder_id"]), match_method="trigram",
                              match_score=match.score)
            await queue.finish(conn, row, "skipped", funder_id=prior["resolved_funder_id"])
            return "skipped", None
        if match.method == "trigram" and decided != "rejected":  # a rejected close name is researched as its own funder
            reason = "a close name in Sangam; a person decides whether it is the same funder"
            await record_item(conn, run_id, SOURCE, "funder", "queued", reason=reason, subject=row["name"],
                              match_method="trigram", match_score=match.score)
            await conn.execute(
                "INSERT INTO resolution_queue (raw_name, entity_kind, context, candidates, source) "
                "VALUES (%s, 'funder', %s::jsonb, %s::jsonb, %s) ON CONFLICT DO NOTHING",
                (row["name"], json.dumps({"pool_funder_id": row["pool_funder_id"], "category": row["category"]}),
                 json.dumps(match.candidates), SOURCE))
            await queue.finish(conn, row, "needs_review", error=reason)
            return "needs_review", reason

    summaries = await research(row)
    slugs = [s["slug"] for s in summaries if s.get("slug") and s.get("saved") is not False]
    async with pool.connection() as conn, conn.transaction():
        if summaries and not slugs:
            raise RuntimeError(f"researchers ran but saved nothing (researchers: {len(summaries)})")
        if not slugs:
            earlier = await (await conn.execute(EARLIER, {"name": row["name"]})).fetchone()
            slugs = [earlier["slug"]] if earlier else []
        await conn.execute(
            "UPDATE entity_research SET run_id = %s "
            "WHERE slug = ANY(%s) AND researched_on = current_date AND run_id IS NULL", (run_id, slugs))
        saved = await (await conn.execute(IDENTITY_CIN, (slugs,))).fetchall()
        if not saved:
            raise RuntimeError(f"research saved nothing (researchers: {len(summaries)})")
        found = pick(saved, row["name"])
        status, error = verdict(found)
        holder = await cin_holder(conn, found["cin"]) if found["cin"] else None
        if holder:
            status, error = "needs_review", f"CIN {found['cin']} is already on {holder['name']} [funder:{holder['id']}]"
        await record_item(conn, run_id, SOURCE, "funder", "queued", reason=error or "research saved; waits for Review",
                          subject=row["name"], target_table="entity_research", target_id=found["slug"],
                          match_method="none")
        await queue.finish(conn, row, status, cin=found["cin"], error=error)
    return status, error


def verdict(saved: dict[str, Any]) -> tuple[str, str | None]:
    """Research that found the funder is done; research that did not waits for a person."""
    if saved["status"] == "unmatched":
        return "needs_review", "research saved for other entities, none matching this funder"
    if saved["status"] in ("complete", "partial"):
        return "done", None
    return "needs_review", f"research ended {saved['status']}"


def pick(saved: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """This row's own research; with several researched and none named, status 'unmatched' and no CIN, never a parent's."""
    usable = [r for r in saved if r["status"] != "wrong_entity"] or saved
    names = {name.casefold()}
    named = [r for r in usable if {(r["entity_name"] or "").casefold(), (r.get("canonical_name") or "").casefold()} & names]
    if named:
        return next((r for r in named if r["cin"]), named[0])
    if len(usable) == 1:
        return usable[0]
    return {**usable[0], "cin": None, "status": "unmatched"}

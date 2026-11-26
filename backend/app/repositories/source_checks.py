"""Change check runs and what each found per source, for the Scout screen."""

from __future__ import annotations

from typing import Any
from uuid import UUID

RUN_COLUMNS = """
    r.run_id, r.slug, r.depth, r.decision, r.started_at, r.finished_at, r.error, r.refresh_row_id,
    r.refresh_summary, u.email AS requested_by,
    (SELECT count(*) FROM source_checks c WHERE c.run_id = r.run_id) AS sources
"""

RUNS_SQL = f"""
    SELECT {RUN_COLUMNS} FROM source_check_runs r LEFT JOIN users u ON u.id = r.requested_by
     WHERE r.slug = %s ORDER BY r.started_at DESC LIMIT %s
"""
RUN_SQL = f"SELECT {RUN_COLUMNS} FROM source_check_runs r LEFT JOIN users u ON u.id = r.requested_by WHERE r.run_id = %s"
ROWS_SQL = """
    SELECT c.url, c.status, c.detail, c.findings_intact, c.findings_broken, c.findings_unanchored, c.judge,
           c.removed_text, c.added_text, c.evidence, c.baseline_snapshot_id, c.new_snapshot_id,
           b.first_seen_at AS baseline_seen_at, b.text_hash AS baseline_hash,
           -- Unchanged means today's text hashed to the kept copy's; a page that differed has its own new version.
           CASE WHEN c.status = 'unchanged' THEN b.text_hash ELSE n.text_hash END AS today_hash
      FROM source_checks c
      LEFT JOIN source_snapshots b ON b.id = c.baseline_snapshot_id
      LEFT JOIN source_snapshots n ON n.id = c.new_snapshot_id
     WHERE c.run_id = %s
     ORDER BY CASE c.status WHEN 'changed' THEN 0 WHEN 'dead' THEN 1 WHEN 'new' THEN 2 WHEN 'differs' THEN 3
                            WHEN 'minor' THEN 4 WHEN 'unverified' THEN 5 ELSE 6 END, c.url
"""

# Every saved entity a change check can run on, by the catalog row research was saved to: a research slug and a
# Registry slug are made apart (pratham vs pratham-2), so only the id names the same organisation.
TRACKED_SQL = """
    SELECT slug, kind, id, sources, last_checked FROM (
        SELECT r.slug, count(DISTINCT s.url) AS sources,
               (SELECT max(c.finished_at) FROM source_check_runs c WHERE c.slug = r.slug AND c.error IS NULL)
                   AS last_checked
          FROM entity_research r
         CROSS JOIN LATERAL unnest(r.snapshot_ids) AS sid
          JOIN source_snapshots s ON s.id = sid
         WHERE r.status <> 'wrong_entity'
         GROUP BY r.slug
    ) t
    CROSS JOIN LATERAL (
        -- The kind and id come from the newest row that was saved, not the newest row: a refresh row is not saved
        -- yet, and a later run that found nothing has kind 'unknown'.
        SELECT CASE WHEN x.resolved_funder_id IS NOT NULL THEN 'funder' ELSE 'org' END AS kind,
               coalesce(x.resolved_funder_id, x.resolved_org_id) AS id
          FROM entity_research x
         WHERE x.slug = t.slug AND x.status <> 'wrong_entity'
           AND (x.resolved_funder_id IS NOT NULL OR x.resolved_org_id IS NOT NULL)
         ORDER BY x.researched_at DESC
         LIMIT 1
    ) saved
"""


NAME_SQL = """
    SELECT coalesce(canonical_name, entity_name) AS name FROM entity_research
     WHERE slug = %s AND status <> 'wrong_entity'
     ORDER BY researched_on DESC, id DESC
     LIMIT 1
"""


async def entity_name(conn: Any, slug: str) -> str | None:
    """The name the newest research gave the entity, for the screen's heading."""
    row = await (await conn.execute(NAME_SQL, (slug,))).fetchone()
    return row["name"] if row else None


async def list_tracked(conn: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in await (await conn.execute(TRACKED_SQL)).fetchall()]


async def list_runs(conn: Any, slug: str, limit: int = 20) -> list[dict[str, Any]]:
    return [dict(r) for r in await (await conn.execute(RUNS_SQL, (slug, limit))).fetchall()]


async def get_run(conn: Any, run_id: UUID) -> dict[str, Any] | None:
    row = await (await conn.execute(RUN_SQL, (run_id,))).fetchone()
    if row is None:
        return None
    rows = await (await conn.execute(ROWS_SQL, (run_id,))).fetchall()
    return {**dict(row), "checks": [dict(r) for r in rows]}

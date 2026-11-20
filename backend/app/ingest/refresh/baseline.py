"""The baseline: for each URL an entity's facts came from, the version of it they were read from."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# One row per URL: the snapshot in the newest research row that read it, so a narrow re-run keeps older URLs.
BASELINE_SQL = """
    SELECT DISTINCT ON (s.url)
           s.url, s.id AS snapshot_id, s.kind, s.text_hash, s.archive_key,
           r.id AS research_id, r.researched_on
      FROM entity_research r
     CROSS JOIN LATERAL unnest(r.snapshot_ids) AS read(snapshot_id)
      JOIN source_snapshots s ON s.id = read.snapshot_id
     WHERE r.slug = %s AND r.status <> 'wrong_entity'
     ORDER BY s.url, r.researched_on DESC, r.id DESC, s.last_seen_at DESC
"""

# Research saved before snapshots were recorded: its sources can't be checked, only re-researched.
UNRECORDED_SQL = """
    SELECT count(*) AS n FROM entity_research
     WHERE slug = %s AND status <> 'wrong_entity' AND snapshot_ids IS NULL
"""


@dataclass(frozen=True)
class Baseline:
    url: str
    snapshot_id: int
    kind: str | None
    text_hash: str
    archive_key: str | None
    research_id: int
    researched_on: date


async def load(conn: Any, slug: str) -> tuple[list[Baseline], int]:
    """The baseline of every URL the slug's research read, and how many of its rows predate snapshots."""
    rows = await (await conn.execute(BASELINE_SQL, (slug,))).fetchall()
    unrecorded = await (await conn.execute(UNRECORDED_SQL, (slug,))).fetchone()
    return [Baseline(**r) for r in rows], (unrecorded or {}).get("n", 0)


def describe(slug: str, baselines: list[Baseline], unrecorded: int) -> str:
    if not baselines:
        lines = [f"{slug}: nothing to check: no research row records what it read. Run a full pull first."]
    else:
        lines = [f"{slug}: {len(baselines)} sources to check"]
        lines += [f"  {b.researched_on}  {b.kind or '?':8}  {b.text_hash[:12]}  "
                  f"{'archived' if b.archive_key else 'no archive'}  {b.url}" for b in baselines]
    if unrecorded:
        lines.append(f"  ({unrecorded} research rows predate snapshots; their sources are not checked)")
    return "\n".join(lines)

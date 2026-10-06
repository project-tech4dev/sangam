"""Files each programme under a Schedule VII clause, so stage 1 can compare programmes in SQL."""

from __future__ import annotations

from typing import Any

from app.ingest.taxonomy import clause_for

TAGGED_BY = "taxonomy.clause_for"


async def backfill_programme_themes(conn: Any) -> int:
    """Tag every untagged programme whose words place it; returns rows written. Idempotent."""
    tag_ids = {r["slug"]: r["id"] for r in await (await conn.execute(
        "SELECT slug, id FROM tags WHERE kind = 'csr_sector'")).fetchall()}
    programmes = await (await conn.execute(
        "SELECT p.id, p.name, p.description FROM programs p "
        "WHERE NOT EXISTS (SELECT 1 FROM program_tags pt WHERE pt.program_id = p.id)")).fetchall()
    written = 0
    for p in programmes:
        slug = clause_for(f"{p['name'] or ''} {p['description'] or ''}")
        if slug is None or slug not in tag_ids:
            continue
        cur = await conn.execute(
            "INSERT INTO program_tags (program_id, tag_id, role, is_inferred, tagged_by) "
            "VALUES (%s, %s, 'primary', true, %s) ON CONFLICT DO NOTHING",
            (p["id"], tag_ids[slug], TAGGED_BY))
        written += cur.rowcount
    return written

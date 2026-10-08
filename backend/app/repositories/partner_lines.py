from __future__ import annotations

from typing import Any

# The backend connects as the owner, so RLS does not apply here: is_public is the filter.
# fy_is_dated is false when 0034 or the seed fell back to the day the source was read or the row recorded.
BASE = """
SELECT a.id, a.funder_id, f.slug AS funder_slug, f.name AS funder_name, a.fiscal_year,
       a.partner_name, o.id AS partner_org_id, o.slug AS partner_org_slug, o.name AS partner_org_name,
       a.project_name, a.program_id, p.name AS program_name, a.amount, a.start_date, a.end_date,
       a.relationship_status, a.notes, a.source_name, a.source_url, a.fetched_at,
       (strpos(coalesce(a.notes, ''), 'fiscal_year is the year the source was read') = 0
        AND strpos(coalesce(a.notes, ''), 'fiscal_year is the year the row was recorded') = 0) AS fy_is_dated,
       COUNT(*) OVER () AS total
FROM funder_activity a
JOIN funders f ON f.id = a.funder_id
LEFT JOIN orgs o ON o.id = a.partner_org_id
LEFT JOIN programs p ON p.id = a.program_id
WHERE a.kind = 'partner' AND a.is_public
"""


async def list_partner_lines(pool: Any, *, limit: int, offset: int, funder: str | None = None,
                             org: str | None = None, status: str | None = None) -> tuple[list[dict], int]:
    sql = BASE + """
      AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      AND (%(status)s::text IS NULL OR a.relationship_status = %(status)s)
    ORDER BY a.start_date DESC NULLS LAST, a.fiscal_year DESC, a.id
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "funder": funder, "org": org, "status": status}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def get_partner_line(pool: Any, line_id: int) -> dict | None:
    async with pool.connection() as conn:
        return await (await conn.execute(BASE + " AND a.id = %s", (line_id,))).fetchone()

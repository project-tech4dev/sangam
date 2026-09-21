from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

BASE = """
SELECT g.*, f.name AS funder_name, o.name AS org_name, p.name AS program_name,
       COUNT(*) OVER () AS total
FROM grants g
JOIN funders f ON f.id = g.funder_id
JOIN orgs o ON o.id = g.org_id
LEFT JOIN programs p ON p.id = g.program_id
"""


async def list_grants(pool: AsyncConnectionPool, *, limit: int, offset: int,
                      status: str | None = None, funder: str | None = None,
                      org: str | None = None) -> tuple[list[dict], int]:
    sql = BASE + """
    WHERE (%(status)s::text IS NULL OR g.status = %(status)s)
      AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
    ORDER BY g.start_date DESC NULLS LAST, g.id
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "status": status, "funder": funder, "org": org}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def get_grant(pool: AsyncConnectionPool, grant_id: int) -> dict | None:
    async with pool.connection() as conn:
        return await (
            await conn.execute(BASE + " WHERE g.id = %s", (grant_id,))
        ).fetchone()

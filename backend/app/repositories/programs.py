from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

BASE = """
SELECT p.*, o.name AS org_name, f.name AS funder_name,
       COUNT(*) OVER () AS total
FROM programs p
LEFT JOIN orgs o ON o.id = p.org_id
LEFT JOIN funders f ON f.id = p.funder_id
"""


async def list_programs(pool: AsyncConnectionPool, *, limit: int, offset: int,
                        funder: str | None = None, org: str | None = None,
                        status: str | None = None) -> tuple[list[dict], int]:
    sql = BASE + """
    WHERE (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      AND (%(status)s::text IS NULL OR p.status = %(status)s)
    ORDER BY p.name
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "funder": funder, "org": org, "status": status}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def get_program(pool: AsyncConnectionPool, program_id: int) -> dict | None:
    async with pool.connection() as conn:
        return await (
            await conn.execute(BASE + " WHERE p.id = %s", (program_id,))
        ).fetchone()

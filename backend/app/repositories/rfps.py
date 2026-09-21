from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

BASE = """
SELECT r.*, f.name AS funder_name, COUNT(*) OVER () AS total
FROM rfps r
LEFT JOIN funders f ON f.id = r.funder_id
"""


async def list_rfps(pool: AsyncConnectionPool, *, limit: int, offset: int,
                    status: str | None = None, deadline_before: str | None = None,
                    tag: str | None = None) -> tuple[list[dict], int]:
    sql = BASE + """
    WHERE (%(status)s::text IS NULL OR r.status = %(status)s)
      AND (%(deadline_before)s::date IS NULL OR r.deadline <= %(deadline_before)s::date)
      AND (%(tag)s::text IS NULL OR EXISTS (
            SELECT 1 FROM rfp_tags rt JOIN tags tg ON tg.id = rt.tag_id
            WHERE rt.rfp_id = r.id AND (tg.slug = %(tag)s OR tg.label ILIKE %(tag)s)))
    ORDER BY r.deadline ASC NULLS LAST, r.id
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "status": status,
              "deadline_before": deadline_before, "tag": tag}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def get_rfp(pool: AsyncConnectionPool, rfp_id: int) -> dict | None:
    async with pool.connection() as conn:
        return await (await conn.execute(BASE + " WHERE r.id = %s", (rfp_id,))).fetchone()


async def list_matches(pool: AsyncConnectionPool, rfp_id: int) -> list[dict]:
    async with pool.connection() as conn:
        return await (
            await conn.execute(
                """
                SELECT m.*, o.name AS org_name
                FROM rfp_matches m JOIN orgs o ON o.id = m.org_id
                WHERE m.rfp_id = %s
                ORDER BY m.match_score DESC NULLS LAST
                """,
                (rfp_id,),
            )
        ).fetchall()


async def update_match(pool: AsyncConnectionPool, rfp_id: int, org_id: int, *,
                       status: str, match_notes: str | None, matched_by: str) -> dict | None:
    async with pool.connection() as conn:
        return await (
            await conn.execute(
                """
                UPDATE rfp_matches
                SET status = %s, match_notes = COALESCE(%s, match_notes), matched_by = %s
                WHERE rfp_id = %s AND org_id = %s
                RETURNING *
                """,
                (status, match_notes, matched_by, rfp_id, org_id),
            )
        ).fetchone()

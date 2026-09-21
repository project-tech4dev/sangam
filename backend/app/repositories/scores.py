from __future__ import annotations

from uuid import UUID

from psycopg_pool import AsyncConnectionPool

BASE = """
SELECT fs.*, o.name AS org_name, f.name AS funder_name, r.version AS rubric_version,
       COUNT(*) OVER () AS total
FROM fit_scores fs
JOIN orgs o ON o.id = fs.org_id
JOIN funders f ON f.id = fs.funder_id
JOIN rubrics r ON r.id = fs.rubric_id
"""


async def list_scores(pool: AsyncConnectionPool, *, limit: int, offset: int,
                      org: str | None = None, funder: str | None = None,
                      rubric: str | None = None) -> tuple[list[dict], int]:
    sql = BASE + """
    WHERE (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(rubric)s::text IS NULL OR r.version = %(rubric)s)
    ORDER BY r.version, fs.total_score DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "org": org, "funder": funder, "rubric": rubric}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def get_score(pool: AsyncConnectionPool, fit_score_id: int) -> dict | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(BASE + " WHERE fs.id = %s", (fit_score_id,))
        ).fetchone()
        if row is None:
            return None
        row["items"] = await (
            await conn.execute(
                """
                SELECT rc.code, rc.label, rc.points, fsi.score, fsi.justification
                FROM fit_score_items fsi
                JOIN rubric_criteria rc ON rc.id = fsi.criterion_id
                WHERE fsi.fit_score_id = %s
                ORDER BY rc.code
                """,
                (fit_score_id,),
            )
        ).fetchall()
        row["adjustments"] = await (
            await conn.execute(
                """
                SELECT sa.*, rc.code
                FROM score_adjustments sa
                JOIN rubric_criteria rc ON rc.id = sa.criterion_id
                WHERE sa.fit_score_id = %s
                ORDER BY sa.adjusted_at
                """,
                (fit_score_id,),
            )
        ).fetchall()
    return row


async def create_adjustment(pool: AsyncConnectionPool, fit_score_id: int, data: dict,
                            adjusted_by: UUID) -> dict | None:
    """Returns the created row, or None when the fit_score doesn't exist."""
    async with pool.connection() as conn:
        exists = await (
            await conn.execute("SELECT 1 FROM fit_scores WHERE id = %s", (fit_score_id,))
        ).fetchone()
        if exists is None:
            return None
        return await (
            await conn.execute(
                """
                INSERT INTO score_adjustments (fit_score_id, criterion_id, old_score,
                                               new_score, reason, adjusted_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (fit_score_id, data["criterion_id"], data.get("old_score"),
                 data["new_score"], data["reason"], adjusted_by),
            )
        ).fetchone()

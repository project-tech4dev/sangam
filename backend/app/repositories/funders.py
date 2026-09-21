"""Funder queries. Legacy-compat computed fields: focus_sectors from funder_tags,
geographies from funder_locations, latest_scores per rubric version."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

LATEST_SCORES_SQL = """
COALESCE(
  (SELECT jsonb_object_agg(sub.version, sub.total_score)
   FROM (
     SELECT DISTINCT ON (r.version) r.version, fs.total_score
     FROM fit_scores fs JOIN rubrics r ON r.id = fs.rubric_id
     WHERE fs.funder_id = f.id
     ORDER BY r.version, fs.scored_at DESC
   ) sub),
  '{}'::jsonb
) AS latest_scores
"""

LIST_SQL = f"""
SELECT f.id, f.slug, f.name, f.funder_type, f.website, f.profile,
       COALESCE(t.focus_sectors, '{{}}') AS focus_sectors,
       COALESCE(l.geographies, '{{}}') AS geographies,
       {LATEST_SCORES_SQL},
       COUNT(*) OVER () AS total
FROM funders f
LEFT JOIN LATERAL (
  SELECT array_agg(tg.label ORDER BY ft.role, tg.label) AS focus_sectors
  FROM funder_tags ft JOIN tags tg ON tg.id = ft.tag_id WHERE ft.funder_id = f.id
) t ON true
LEFT JOIN LATERAL (
  SELECT array_agg(lo.name ORDER BY lo.kind, lo.name) AS geographies
  FROM funder_locations fl JOIN locations lo ON lo.id = fl.location_id
  WHERE fl.funder_id = f.id
) l ON true
WHERE (%(tag)s::text IS NULL OR EXISTS (
        SELECT 1 FROM funder_tags ft2 JOIN tags tg2 ON tg2.id = ft2.tag_id
        WHERE ft2.funder_id = f.id AND (tg2.slug = %(tag)s OR tg2.label ILIKE %(tag)s)))
  AND (%(section_135)s::boolean IS NULL OR f.section_135_bound IS NOT DISTINCT FROM %(section_135)s)
ORDER BY f.name
LIMIT %(limit)s OFFSET %(offset)s
"""


async def list_funders(pool: AsyncConnectionPool, *, limit: int, offset: int,
                       tag: str | None = None, section_135: bool | None = None) -> tuple[list[dict], int]:
    params = {"limit": limit, "offset": offset, "tag": tag, "section_135": section_135}
    async with pool.connection() as conn:
        rows = await (await conn.execute(LIST_SQL, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def get_funder(pool: AsyncConnectionPool, slug_or_id: str) -> dict | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                f"""
                SELECT f.*, COALESCE(t.focus_sectors, '{{}}') AS focus_sectors,
                       COALESCE(l.geographies, '{{}}') AS geographies,
                       {LATEST_SCORES_SQL}
                FROM funders f
                LEFT JOIN LATERAL (
                  SELECT array_agg(tg.label ORDER BY ft.role, tg.label) AS focus_sectors
                  FROM funder_tags ft JOIN tags tg ON tg.id = ft.tag_id WHERE ft.funder_id = f.id
                ) t ON true
                LEFT JOIN LATERAL (
                  SELECT array_agg(lo.name ORDER BY lo.kind, lo.name) AS geographies
                  FROM funder_locations fl JOIN locations lo ON lo.id = fl.location_id
                  WHERE fl.funder_id = f.id
                ) l ON true
                WHERE f.slug = %(v)s OR f.id::text = %(v)s
                """,
                {"v": slug_or_id},
            )
        ).fetchone()
        if row is None:
            return None
        funder_id = row["id"]
        row["identifiers"] = await (
            await conn.execute(
                "SELECT id_type, id_value, verified, source_url FROM funder_identifiers "
                "WHERE funder_id = %s ORDER BY id_type",
                (funder_id,),
            )
        ).fetchall()
        row["tags"] = await (
            await conn.execute(
                "SELECT tg.slug, tg.label, ft.role FROM funder_tags ft "
                "JOIN tags tg ON tg.id = ft.tag_id WHERE ft.funder_id = %s ORDER BY ft.role, tg.label",
                (funder_id,),
            )
        ).fetchall()
        row["locations"] = await (
            await conn.execute(
                "SELECT l.id, l.kind, l.name, fl.role FROM funder_locations fl "
                "JOIN locations l ON l.id = fl.location_id WHERE fl.funder_id = %s",
                (funder_id,),
            )
        ).fetchall()
        row["contacts"] = await (
            await conn.execute(
                "SELECT * FROM contacts WHERE funder_id = %s ORDER BY kind, name", (funder_id,)
            )
        ).fetchall()
    return row


async def funder_scores(pool: AsyncConnectionPool, funder_id: int) -> list[dict]:
    async with pool.connection() as conn:
        return await (
            await conn.execute(
                """
                SELECT fs.id, o.name AS org_name, r.version AS rubric_version,
                       fs.total_score, fs.max_score, fs.scored_by, fs.scored_at, fs.notes
                FROM fit_scores fs
                JOIN orgs o ON o.id = fs.org_id
                JOIN rubrics r ON r.id = fs.rubric_id
                WHERE fs.funder_id = %s
                ORDER BY r.version, fs.scored_at DESC
                """,
                (funder_id,),
            )
        ).fetchall()

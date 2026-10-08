"""Org queries. Legacy-compat computed fields: darpan_id from org_identifiers, state/district from the
registered location's parent chain, sectors from"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

LIST_SQL = """
SELECT o.id, o.slug, o.name, o.cohort, o.source_name, o.source_url, o.fetched_at,
       di.id_value AS darpan_id,
       dl.name AS district, sl.name AS state,
       COALESCE(t.sectors, '{}') AS sectors,
       COUNT(*) OVER () AS total
FROM orgs o
LEFT JOIN LATERAL (
  SELECT id_value FROM org_identifiers
  WHERE org_id = o.id AND id_type = 'darpan' AND id_value IS NOT NULL
  ORDER BY is_current DESC, id LIMIT 1
) di ON true
LEFT JOIN locations dl ON dl.id = o.registered_location_id
LEFT JOIN locations sl ON sl.id = dl.parent_id
LEFT JOIN LATERAL (
  SELECT array_agg(tg.label ORDER BY ot.role, tg.label) AS sectors
  FROM org_tags ot JOIN tags tg ON tg.id = ot.tag_id WHERE ot.org_id = o.id
) t ON true
WHERE (%(q)s::text IS NULL OR o.name ILIKE '%%' || %(q)s || '%%' OR similarity(o.name, %(q)s) > 0.3)
  AND (%(state)s::text IS NULL OR sl.name ILIKE %(state)s)
  AND (%(district)s::text IS NULL OR dl.name ILIKE %(district)s)
  AND (%(tag)s::text IS NULL OR EXISTS (
        SELECT 1 FROM org_tags ot2 JOIN tags tg2 ON tg2.id = ot2.tag_id
        WHERE ot2.org_id = o.id AND (tg2.slug = %(tag)s OR tg2.label ILIKE %(tag)s)))
ORDER BY o.name
LIMIT %(limit)s OFFSET %(offset)s
"""


async def list_orgs(pool: AsyncConnectionPool, *, limit: int, offset: int,
                    tag: str | None = None, state: str | None = None,
                    district: str | None = None, q: str | None = None) -> tuple[list[dict], int]:
    params = {"limit": limit, "offset": offset, "tag": tag, "state": state,
              "district": district, "q": q}
    async with pool.connection() as conn:
        rows = await (await conn.execute(LIST_SQL, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def get_org(pool: AsyncConnectionPool, slug_or_id: str) -> dict | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT o.*, di.id_value AS darpan_id, dl.name AS district, sl.name AS state,
                       COALESCE(t.sectors, '{}') AS sectors
                FROM orgs o
                LEFT JOIN LATERAL (
                  SELECT id_value FROM org_identifiers
                  WHERE org_id = o.id AND id_type = 'darpan' AND id_value IS NOT NULL
                  ORDER BY is_current DESC, id LIMIT 1
                ) di ON true
                LEFT JOIN locations dl ON dl.id = o.registered_location_id
                LEFT JOIN locations sl ON sl.id = dl.parent_id
                LEFT JOIN LATERAL (
                  SELECT array_agg(tg.label ORDER BY ot.role, tg.label) AS sectors
                  FROM org_tags ot JOIN tags tg ON tg.id = ot.tag_id WHERE ot.org_id = o.id
                ) t ON true
                WHERE o.slug = %(v)s OR o.id::text = %(v)s
                """,
                {"v": slug_or_id},
            )
        ).fetchone()
        if row is None:
            return None
        org_id = row["id"]
        row["identifiers"] = await (
            await conn.execute(
                "SELECT id, id_type, id_value, status, valid_from, valid_until, application_ref, "
                "check_method, verified, is_current, source_type, evidence, source_url "
                "FROM org_identifiers WHERE org_id = %s "
                "ORDER BY id_type, is_current DESC, (id_value IS NULL), id",
                (org_id,),
            )
        ).fetchall()
        row["tags"] = await (
            await conn.execute(
                "SELECT tg.slug, tg.label, ot.role FROM org_tags ot "
                "JOIN tags tg ON tg.id = ot.tag_id WHERE ot.org_id = %s ORDER BY ot.role, tg.label",
                (org_id,),
            )
        ).fetchall()
        row["locations"] = await (
            await conn.execute(
                "SELECT l.id, l.kind, l.name, ol.role FROM org_locations ol "
                "JOIN locations l ON l.id = ol.location_id WHERE ol.org_id = %s",
                (org_id,),
            )
        ).fetchall()
        row["contacts"] = await (
            await conn.execute(
                "SELECT * FROM contacts WHERE org_id = %s ORDER BY kind, name", (org_id,)
            )
        ).fetchall()
    return row

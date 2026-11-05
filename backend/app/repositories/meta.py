from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from app.repositories.paging import fetch_page


async def list_tags(pool: AsyncConnectionPool, *, limit: int, offset: int,
                    kind: str | None = None, q: str | None = None) -> tuple[list[dict], int]:
    sql = """
    SELECT t.*, COUNT(*) OVER () AS total
    FROM tags t
    WHERE (%(kind)s::text IS NULL OR t.kind = %(kind)s)
      AND (%(q)s::text IS NULL OR t.label ILIKE '%%' || %(q)s || '%%' OR t.slug ILIKE '%%' || %(q)s || '%%')
    ORDER BY t.label
    """
    return await fetch_page(pool, sql, {"kind": kind, "q": q}, limit=limit, offset=offset)


async def list_locations(pool: AsyncConnectionPool, *, limit: int, offset: int,
                         kind: str | None = None, parent: int | None = None) -> tuple[list[dict], int]:
    sql = """
    SELECT l.*, p.name AS parent_name, COUNT(*) OVER () AS total
    FROM locations l
    LEFT JOIN locations p ON p.id = l.parent_id
    WHERE (%(kind)s::text IS NULL OR l.kind = %(kind)s)
      AND (%(parent)s::bigint IS NULL OR l.parent_id = %(parent)s)
    ORDER BY l.kind, l.name
    """
    return await fetch_page(pool, sql, {"kind": kind, "parent": parent}, limit=limit, offset=offset)


async def stats(pool: AsyncConnectionPool) -> dict:
    sql = """
    SELECT
      (SELECT count(*) FROM orgs)          AS orgs,
      (SELECT count(*) FROM funders)       AS funders,
      (SELECT count(*) FROM funder_activity
         WHERE kind = 'partner' AND partner_org_id IS NOT NULL
           AND (amount IS NOT NULL OR relationship_status IS NOT NULL)) AS grants,
      (SELECT count(*) FROM fit_scores)    AS fit_scores,
      (SELECT count(*) FROM programs)      AS programs,
      (SELECT count(*) FROM contacts)      AS contacts,
      (SELECT count(*) FROM documents)     AS documents,
      (SELECT count(*) FROM news_stories)  AS news_stories,
      (SELECT count(DISTINCT l.id) FROM org_locations ol
         JOIN locations l ON l.id = ol.location_id AND l.kind = 'district') AS districts_covered
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql)).fetchone()

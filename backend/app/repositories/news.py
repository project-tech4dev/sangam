from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


async def list_news(pool: AsyncConnectionPool, *, limit: int, offset: int,
                    org: str | None = None, funder: str | None = None,
                    topic: str | None = None) -> tuple[list[dict], int]:
    sql = """
    SELECT n.*, COUNT(*) OVER () AS total
    FROM news_mentions n
    LEFT JOIN orgs o ON o.id = n.org_id
    LEFT JOIN funders f ON f.id = n.funder_id
    WHERE (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(topic)s::text IS NULL OR n.topic = %(topic)s)
    ORDER BY n.seendate DESC NULLS LAST
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "org": org, "funder": funder, "topic": topic}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def stats(pool: AsyncConnectionPool) -> dict:
    sql = """
    SELECT
      (SELECT count(*) FROM orgs)          AS orgs,
      (SELECT count(*) FROM funders)       AS funders,
      (SELECT count(*) FROM grants)        AS grants,
      (SELECT count(*) FROM fit_scores)    AS fit_scores,
      (SELECT count(*) FROM programs)      AS programs,
      (SELECT count(*) FROM contacts)      AS contacts,
      (SELECT count(*) FROM documents)     AS documents,
      (SELECT count(*) FROM news_mentions) AS news_mentions,
      (SELECT count(DISTINCT l.id) FROM org_locations ol
         JOIN locations l ON l.id = ol.location_id AND l.kind = 'district') AS districts_covered
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql)).fetchone()

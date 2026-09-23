from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


async def list_documents(pool: AsyncConnectionPool, *, limit: int, offset: int,
                         org: str | None = None, funder: str | None = None,
                         doc_type: str | None = None) -> tuple[list[dict], int]:
    sql = """
    SELECT d.id, d.org_id, d.funder_id, d.title, d.doc_type,
           d.source_name, d.source_url, d.fetched_at,
           COUNT(*) OVER () AS total
    FROM documents d
    LEFT JOIN orgs o ON o.id = d.org_id
    LEFT JOIN funders f ON f.id = d.funder_id
    WHERE (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)
    ORDER BY d.title NULLS LAST
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "org": org, "funder": funder, "doc_type": doc_type}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)

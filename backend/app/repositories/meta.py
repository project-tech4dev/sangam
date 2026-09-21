from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


async def list_tags(pool: AsyncConnectionPool, *, limit: int, offset: int,
                    kind: str | None = None, q: str | None = None) -> tuple[list[dict], int]:
    sql = """
    SELECT t.*, COUNT(*) OVER () AS total
    FROM tags t
    WHERE (%(kind)s::text IS NULL OR t.kind = %(kind)s)
      AND (%(q)s::text IS NULL OR t.label ILIKE '%%' || %(q)s || '%%' OR t.slug ILIKE '%%' || %(q)s || '%%')
    ORDER BY t.label
    LIMIT %(limit)s OFFSET %(offset)s
    """
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, {"limit": limit, "offset": offset,
                                               "kind": kind, "q": q})).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


async def list_locations(pool: AsyncConnectionPool, *, limit: int, offset: int,
                         kind: str | None = None, parent: int | None = None) -> tuple[list[dict], int]:
    sql = """
    SELECT l.*, p.name AS parent_name, COUNT(*) OVER () AS total
    FROM locations l
    LEFT JOIN locations p ON p.id = l.parent_id
    WHERE (%(kind)s::text IS NULL OR l.kind = %(kind)s)
      AND (%(parent)s::bigint IS NULL OR l.parent_id = %(parent)s)
    ORDER BY l.kind, l.name
    LIMIT %(limit)s OFFSET %(offset)s
    """
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, {"limit": limit, "offset": offset,
                                               "kind": kind, "parent": parent})).fetchall()
    return rows, (rows[0]["total"] if rows else 0)

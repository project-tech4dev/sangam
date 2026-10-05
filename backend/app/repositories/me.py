from __future__ import annotations

from uuid import UUID

from psycopg_pool import AsyncConnectionPool


async def list_memberships(pool: AsyncConnectionPool, user_id: UUID) -> list[dict]:
    sql = """
    SELECT m.org_id, o.slug AS org_slug, o.name AS org_name, m.role
    FROM org_members m
    JOIN orgs o ON o.id = m.org_id
    WHERE m.user_id = %s
    ORDER BY o.name
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql, (user_id,))).fetchall()

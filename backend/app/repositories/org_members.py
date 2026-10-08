from __future__ import annotations

from uuid import UUID

from psycopg_pool import AsyncConnectionPool


async def list_members(pool: AsyncConnectionPool, org_id: int) -> list[dict]:
    """The org's members RLS lets the caller see: everyone for its admins and staff, only themselves otherwise."""
    sql = """
    SELECT u.id AS user_id, u.display_name, u.email, m.role
    FROM org_members m
    JOIN users u ON u.id = m.user_id
    WHERE m.org_id = %s
    ORDER BY m.role, coalesce(u.display_name, u.email)
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql, (org_id,))).fetchall()


# The app.* functions (0028) check the caller and keep the org's last admin; their errors carry the message.
async def add_member(pool: AsyncConnectionPool, org_id: int, email: str, role: str) -> None:
    async with pool.connection() as conn:
        await conn.execute("SELECT app.add_org_member(%s, %s, %s)", (org_id, email, role))


async def set_role(pool: AsyncConnectionPool, org_id: int, user_id: UUID, role: str) -> None:
    async with pool.connection() as conn:
        await conn.execute("SELECT app.set_org_member_role(%s, %s, %s)", (org_id, user_id, role))


async def remove_member(pool: AsyncConnectionPool, org_id: int, user_id: UUID) -> None:
    async with pool.connection() as conn:
        await conn.execute("SELECT app.remove_org_member(%s, %s)", (org_id, user_id))

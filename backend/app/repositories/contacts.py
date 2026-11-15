from __future__ import annotations

from psycopg.errors import ForeignKeyViolation
from psycopg_pool import AsyncConnectionPool

from app.repositories.paging import fetch_page

# Whitelist of PATCH-able columns; PATCH builds its SET list only from these.
UPDATABLE = ("name", "role", "kind", "email", "phone", "verified", "notes")


async def list_contacts(pool: AsyncConnectionPool, *, limit: int, offset: int,
                        org: str | None = None, funder: str | None = None,
                        kind: str | None = None, verified: bool | None = None) -> tuple[list[dict], int]:
    sql = """
    SELECT c.*, COUNT(*) OVER () AS total
    FROM contacts c
    LEFT JOIN orgs o ON o.id = c.org_id
    LEFT JOIN funders f ON f.id = c.funder_id
    WHERE (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(kind)s::text IS NULL OR c.kind = %(kind)s)
      AND (%(verified)s::boolean IS NULL OR c.verified = %(verified)s)
    ORDER BY c.name, c.id
    """
    params = {"org": org, "funder": funder, "kind": kind, "verified": verified}
    return await fetch_page(pool, sql, params, limit=limit, offset=offset)


async def get_contact(pool: AsyncConnectionPool, contact_id: int) -> dict | None:
    async with pool.connection() as conn:
        return await (
            await conn.execute("SELECT * FROM contacts WHERE id = %s", (contact_id,))
        ).fetchone()


async def create_contact(pool: AsyncConnectionPool, data: dict) -> dict | None:
    """Returns the created row, or None when the org/funder FK doesn't exist."""
    sql = """
    INSERT INTO contacts (org_id, funder_id, name, role, kind, email, phone, verified,
                          notes, source_name, fetched_at)
    VALUES (%(org_id)s, %(funder_id)s, %(name)s, %(role)s, %(kind)s, %(email)s,
            %(phone)s, %(verified)s, %(notes)s, 'manual', now())
    RETURNING *
    """
    try:
        async with pool.connection() as conn:
            return await (await conn.execute(sql, data)).fetchone()
    except ForeignKeyViolation:
        return None


async def update_contact(pool: AsyncConnectionPool, contact_id: int, fields: dict) -> dict | None:
    sets = [f"{col} = %({col})s" for col in UPDATABLE if col in fields]
    if not sets:
        return await get_contact(pool, contact_id)
    # A person's edit unranks the row (NULL tier = person-entered), so no research ever overwrites it.
    sets += ["source_type = NULL", "evidence = NULL"]
    sql = f"UPDATE contacts SET {', '.join(sets)} WHERE id = %(id)s RETURNING *"
    async with pool.connection() as conn:
        return await (await conn.execute(sql, {**fields, "id": contact_id})).fetchone()

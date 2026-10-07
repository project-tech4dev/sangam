from __future__ import annotations

from uuid import UUID

from psycopg_pool import AsyncConnectionPool


class EmailTakenError(Exception):
    """The email already belongs to a users row linked to a different Supabase account."""

    def __init__(self, email: str, linked_auth_user_id: UUID | None):
        super().__init__(email)
        self.email = email
        self.linked_auth_user_id = linked_auth_user_id


async def resolve_auth_user(
    pool: AsyncConnectionPool, *, auth_user_id: UUID, email: str, display_name: str | None
) -> dict:
    """The users row for a verified Supabase account.

    The sign-up trigger (0022) normally creates it; this creates it if the trigger did not. A row that
    staff pre-created by email, with no auth_user_id yet, is linked rather than duplicated.
    """
    async with pool.connection() as conn, conn.transaction():
        row = await (
            await conn.execute(
                "SELECT id, email, is_staff FROM users WHERE auth_user_id = %s", (auth_user_id,)
            )
        ).fetchone()
        if row:
            if row["email"] != email:
                await conn.execute("UPDATE users SET email = %s WHERE id = %s", (email, row["id"]))
            return {"id": row["id"], "is_staff": row["is_staff"]}

        row = await (
            await conn.execute(
                """
                UPDATE users SET auth_user_id = %s, display_name = coalesce(display_name, %s)
                WHERE email = %s AND auth_user_id IS NULL
                RETURNING id, is_staff
                """,
                (auth_user_id, display_name, email),
            )
        ).fetchone()
        if row:
            return dict(row)

        row = await (
            await conn.execute(
                """
                INSERT INTO users (email, auth_user_id, display_name) VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id, is_staff
                """,
                (email, auth_user_id, display_name),
            )
        ).fetchone()
        if row is None:
            row = await (
                await conn.execute("SELECT id, is_staff FROM users WHERE auth_user_id = %s", (auth_user_id,))
            ).fetchone()
        if row is None:
            linked = await (
                await conn.execute("SELECT auth_user_id FROM users WHERE email = %s", (email,))
            ).fetchone()
            raise EmailTakenError(email, linked["auth_user_id"] if linked else None)
        return dict(row)

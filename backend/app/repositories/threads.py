from __future__ import annotations

from typing import Literal
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from app.db.pool import CallerPool

# Every chat counts, whatever its id: the id is the browser's to choose, and a metered person has only Ask.
ASKED_SQL = "SELECT COALESCE(SUM(questions), 0)::int AS asked FROM threads WHERE user_id = %s"


async def claim_thread(pool: AsyncConnectionPool, *, thread_id: str, user_id: UUID, title: str | None = None,
                       use_case: str = "ask", org_id: int | None = None,
                       limit: int | None = None) -> UUID | None:
    """The thread's owner, making it `user_id` when new, and one more question in it; None at `limit` questions."""
    sql = """
    WITH claimed AS (
      INSERT INTO threads (thread_id, user_id, title, updated_by, use_case, org_id, questions)
      VALUES (%(thread_id)s, %(user_id)s, %(title)s, %(user_id)s, %(use_case)s, %(org_id)s, 1)
      ON CONFLICT (thread_id) DO UPDATE SET
        updated_at = now(),
        updated_by = EXCLUDED.user_id,
        title = COALESCE(threads.title, EXCLUDED.title),
        questions = threads.questions + 1
      WHERE threads.user_id = EXCLUDED.user_id
      RETURNING user_id
    )
    SELECT user_id FROM claimed
    UNION ALL
    SELECT user_id FROM threads WHERE thread_id = %(thread_id)s
    LIMIT 1
    """
    params = {"thread_id": thread_id, "user_id": user_id, "title": title, "use_case": use_case, "org_id": org_id}
    async with pool.connection() as conn, conn.transaction():
        if limit is not None:
            # Held to commit, so two tabs at limit - 1 cannot both get the last question.
            await conn.execute("SELECT 1 FROM users WHERE id = %s FOR UPDATE", (user_id,))
            if (await (await conn.execute(ASKED_SQL, (user_id,))).fetchone())["asked"] >= limit:
                return None
        row = await (await conn.execute(sql, params)).fetchone()
    return row["user_id"]


async def asked(pool: AsyncConnectionPool | CallerPool, *, user_id: UUID) -> int:
    """How many questions the person has asked, in all their chats."""
    async with pool.connection() as conn:
        return (await (await conn.execute(ASKED_SQL, (user_id,))).fetchone())["asked"]


# The only text ever put into list_threads' SQL; an unknown kind fails instead of matching Ask chats.
_KIND_FILTER = {"ask": "NOT LIKE", "import": "LIKE"}


async def list_threads(
    pool: CallerPool, *, user_id: UUID, kind: Literal["ask", "import"] = "ask", limit: int = 50
) -> list[dict]:
    """The caller's own chats of one kind, newest first. Filtered by user too, so staff get theirs, not everyone's."""
    # Import chats are claimed as use_case 'ask' too; their ids are always 'import-<uuid>' (ImportPage.tsx).
    match = _KIND_FILTER[kind]
    sql = f"""
    SELECT thread_id, title, created_at, updated_at FROM threads
    WHERE user_id = %(user_id)s AND use_case = 'ask' AND thread_id {match} 'import-%%'
    ORDER BY updated_at DESC
    LIMIT %(limit)s
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, {"user_id": user_id, "limit": limit})
        return await cur.fetchall()


async def owner_of(pool: AsyncConnectionPool, *, thread_id: str) -> UUID | None:
    """Who claimed the thread; None while no turn has been posted in it."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT user_id FROM threads WHERE thread_id = %s", (thread_id,))
        row = await cur.fetchone()
    return row["user_id"] if row else None


async def can_open(pool: AsyncConnectionPool, *, thread_id: str, user_id: UUID) -> bool:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT app.can_open_thread(%s, %s) AS ok", (thread_id, user_id))
        return bool((await cur.fetchone())["ok"])

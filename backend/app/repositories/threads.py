from __future__ import annotations

from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from app.db.pool import CallerPool


async def claim_thread(pool: AsyncConnectionPool, *, thread_id: str, user_id: UUID, title: str | None = None) -> UUID:
    """The thread's owner, making it `user_id` when the thread is new. An owner's turn bumps updated_at."""
    sql = """
    WITH claimed AS (
      INSERT INTO threads (thread_id, user_id, title, updated_by)
      VALUES (%(thread_id)s, %(user_id)s, %(title)s, %(user_id)s)
      ON CONFLICT (thread_id) DO UPDATE SET
        updated_at = now(),
        updated_by = EXCLUDED.user_id,
        title = COALESCE(threads.title, EXCLUDED.title)
      WHERE threads.user_id = EXCLUDED.user_id
      RETURNING user_id
    )
    SELECT user_id FROM claimed
    UNION ALL
    SELECT user_id FROM threads WHERE thread_id = %(thread_id)s
    LIMIT 1
    """
    params = {"thread_id": thread_id, "user_id": user_id, "title": title}
    async with pool.connection() as conn:
        row = await (await conn.execute(sql, params)).fetchone()
    return row["user_id"]


async def list_threads(pool: CallerPool, *, user_id: UUID, limit: int = 50) -> list[dict]:
    """The caller's own Ask chats, newest first. Filtered by user too, so staff get theirs, not everyone's."""
    # Import chats are claimed as use_case 'ask' too; their ids are always 'import-<uuid>' (ImportWorkspace.tsx).
    sql = """
    SELECT thread_id, title, created_at, updated_at FROM threads
    WHERE user_id = %(user_id)s AND use_case = 'ask' AND thread_id NOT LIKE 'import-%%'
    ORDER BY updated_at DESC
    LIMIT %(limit)s
    """
    async with pool.connection() as conn:
        cur = await conn.execute(sql, {"user_id": user_id, "limit": limit})
        return await cur.fetchall()


async def can_open(pool: AsyncConnectionPool, *, thread_id: str, user_id: UUID) -> bool:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT app.can_open_thread(%s, %s) AS ok", (thread_id, user_id))
        return bool((await cur.fetchone())["ok"])

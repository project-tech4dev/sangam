from __future__ import annotations

from uuid import UUID

from psycopg_pool import AsyncConnectionPool


async def claim_thread(pool: AsyncConnectionPool, *, thread_id: str, user_id: UUID) -> UUID:
    """The thread's owner, making it `user_id` when the thread is new."""
    sql = """
    WITH claimed AS (
      INSERT INTO threads (thread_id, user_id) VALUES (%(thread_id)s, %(user_id)s)
      ON CONFLICT (thread_id) DO NOTHING
      RETURNING user_id
    )
    SELECT user_id FROM claimed
    UNION ALL
    SELECT user_id FROM threads WHERE thread_id = %(thread_id)s
    LIMIT 1
    """
    async with pool.connection() as conn:
        row = await (await conn.execute(sql, {"thread_id": thread_id, "user_id": user_id})).fetchone()
    return row["user_id"]

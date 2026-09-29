from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

_COUNTS = """
SELECT r.id, r.started_at, r.finished_at, r.status,
       count(*) FILTER (WHERE i.status = 'added')    AS added,
       count(*) FILTER (WHERE i.status = 'updated')  AS updated,
       count(*) FILTER (WHERE i.status = 'matched')  AS matched,
       count(*) FILTER (WHERE i.status = 'queued')   AS queued,
       count(*) FILTER (WHERE i.status = 'failed')   AS failed,
       count(*) FILTER (WHERE i.status = 'refused')  AS refused
FROM ingest_runs r
LEFT JOIN ingest_run_items i ON i.run_id = r.id
"""


async def list_runs(pool: AsyncConnectionPool, *, limit: int = 10) -> list[dict]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                f"{_COUNTS} GROUP BY r.id ORDER BY r.started_at DESC LIMIT %s", (limit,)
            )
        ).fetchall()
    return [dict(r) for r in rows]


async def get_run(pool: AsyncConnectionPool, run_id: int) -> dict | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(f"{_COUNTS} WHERE r.id = %s GROUP BY r.id", (run_id,))
        ).fetchone()
    return dict(row) if row else None


async def list_items(pool: AsyncConnectionPool, run_id: int, *, limit: int = 200) -> list[dict]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, source, record_kind, status, subject, reason, target_table, changes, "
                "match_method, match_score, source_url FROM ingest_run_items "
                "WHERE run_id = %s ORDER BY id LIMIT %s",
                (run_id, limit),
            )
        ).fetchall()
    return [dict(r) for r in rows]


async def list_queue(pool: AsyncConnectionPool, *, limit: int = 50) -> list[dict]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, raw_name, entity_kind, source, candidates, source_url, created_at "
                "FROM resolution_queue WHERE status = 'pending' ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        ).fetchall()
    return [dict(r) for r in rows]


async def list_proposals(pool: AsyncConnectionPool, *, limit: int = 50) -> list[dict]:
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, host, first_seen_url, robots_result, times_seen, status, "
                "first_seen_at, last_seen_at FROM ingest_source_proposals "
                "WHERE status = 'proposed' ORDER BY last_seen_at DESC LIMIT %s",
                (limit,),
            )
        ).fetchall()
    return [dict(r) for r in rows]


async def list_research(pool: AsyncConnectionPool, *, limit: int = 50) -> list[dict]:
    """The newest row per entity: re-researching supersedes, it does not stack."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT DISTINCT ON (slug)
                       id, entity_name, canonical_name, entity_kind, slug, status,
                       stopped_reason, summary, fact_count, sources_read, not_found,
                       researched_at
                FROM entity_research
                ORDER BY slug, researched_at DESC
                """
            )
        ).fetchall()
    return sorted(
        (dict(r) for r in rows), key=lambda r: r["researched_at"], reverse=True
    )[:limit]

from __future__ import annotations

from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from app.ingest.source_guards import PRIVATE_URL_LIKE

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


async def list_research(
    pool: AsyncConnectionPool, *, limit: int = 50, mine: tuple[UUID | None, list[int]] | None = None
) -> list[dict]:
    """The newest row per entity: re-researching supersedes, it does not stack.
    `mine` is (user, stewarded org ids): only rows that user saved or about those orgs."""
    where, params = "", ()
    if mine is not None:
        where, params = "WHERE researched_by = %s OR resolved_org_id = ANY(%s)", (mine[0], mine[1])
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                f"""
                SELECT DISTINCT ON (slug)
                       id, entity_name, canonical_name, entity_kind, slug, status,
                       stopped_reason, summary, fact_count, sources_read, not_found,
                       researched_at, saved_at, resolved_org_id, resolved_funder_id,
                       EXISTS (SELECT 1 FROM jsonb_array_elements(findings) f
                               WHERE f->>'source_url' LIKE %s) AS has_private
                FROM entity_research
                {where}
                ORDER BY slug, researched_at DESC
                """,
                (PRIVATE_URL_LIKE, *params),
            )
        ).fetchall()
    return sorted(
        (dict(r) for r in rows), key=lambda r: r["researched_at"], reverse=True
    )[:limit]


# A queued name joins the entity as an alias, which is how the matcher resolves it next run.
_ALIAS_TABLE = {"funder": "funders", "org": "orgs", "location": "locations"}


async def answer_queue(
    pool: AsyncConnectionPool, item_id: int, *, same: bool, candidate_id: int | None, user_id: object
) -> dict | None:
    """Accept (as an alias of the candidate) or reject one pending name. None if not pending or not a candidate."""
    async with pool.connection() as conn, conn.transaction():
        item = await (
            await conn.execute(
                "SELECT id, raw_name, entity_kind, candidates FROM resolution_queue "
                "WHERE id = %s AND status = 'pending' FOR UPDATE",
                (item_id,),
            )
        ).fetchone()
        if item is None:
            return None
        resolved = {"org": None, "funder": None, "location": None}
        if same:
            if candidate_id not in {c.get("id") for c in item["candidates"] or []}:
                return None
            table = _ALIAS_TABLE.get(item["entity_kind"])
            if table:
                # Table name from the constant above; values are parameterised.
                await conn.execute(
                    f"UPDATE {table} SET aliases = array_append(aliases, %s) WHERE id = %s "
                    "AND name <> %s AND NOT %s = ANY(aliases)",
                    (item["raw_name"], candidate_id, item["raw_name"], item["raw_name"]),
                )
                resolved[item["entity_kind"]] = candidate_id
        row = await (
            await conn.execute(
                "UPDATE resolution_queue SET status = %s, resolved_org_id = %s, resolved_funder_id = %s, "
                "resolved_location_id = %s, reviewed_by = %s, reviewed_at = now() "
                "WHERE id = %s RETURNING id, status",
                ("accepted" if same else "rejected", resolved["org"], resolved["funder"],
                 resolved["location"], user_id, item_id),
            )
        ).fetchone()
    return dict(row)

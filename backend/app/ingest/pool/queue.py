"""The funder pool's queue: settings, stale locks, free slots, claims and how a row ends."""

from __future__ import annotations

from typing import Any

SETTINGS = "SELECT * FROM funder_ingest_settings WHERE enabled ORDER BY category"

# A lock older than the timeout was cut off: retry it, or fail it once it has used its attempts.
RECOVER = """
WITH stale AS (
  UPDATE funder_pool p SET
    ingest_status = CASE WHEN p.attempts >= s.max_attempts THEN 'failed' ELSE 'pending' END,
    last_error = 'lock expired after ' || s.lock_timeout_min || ' min', locked_at = NULL, locked_by = NULL,
    updated_at = now()
  FROM funder_ingest_settings s
  WHERE s.category = p.category AND p.category = %(category)s AND p.ingest_status = 'running'
    AND p.locked_at < now() - make_interval(mins => s.lock_timeout_min)
  RETURNING p.last_run_id)
UPDATE ingest_runs SET status = 'failed', finished_at = now(), notes = coalesce(notes, '') || ' · lock expired'
 WHERE id IN (SELECT last_run_id FROM stale) AND status = 'running'
"""

# max_parallel minus what is running, within what is left of today's cap.
FREE = """
SELECT greatest(0, least(
  s.max_parallel - (SELECT count(*) FROM funder_pool WHERE category = s.category AND ingest_status = 'running'),
  coalesce(s.daily_cap - (SELECT count(*) FROM funder_pool WHERE category = s.category
                           AND last_attempt_at >= date_trunc('day', now())), 2147483647))) AS free
FROM funder_ingest_settings s WHERE s.category = %(category)s
"""

CLAIM = """
UPDATE funder_pool SET ingest_status = 'running', locked_at = now(), locked_by = %(worker)s,
       attempts = attempts + 1, last_attempt_at = now(), updated_at = now()
WHERE id IN (
  SELECT p.id FROM funder_pool p JOIN funder_ingest_settings s USING (category)
  WHERE p.category = %(category)s AND p.ingest_status = 'pending'
    AND (s.min_csr_spend_cr IS NULL OR p.csr_spend_3y_avg_cr >= s.min_csr_spend_cr)
  ORDER BY p.priority_override NULLS LAST, p.rank_in_category
  LIMIT %(free)s FOR UPDATE OF p SKIP LOCKED)
RETURNING *
"""


async def enabled_settings(conn: Any) -> list[dict[str, Any]]:
    return await (await conn.execute(SETTINGS)).fetchall()


async def claim(conn: Any, category: str, worker: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Recover this category's stale locks, then claim as many rows as it has free slots, at most limit."""
    async with conn.transaction():
        # Serialises count-then-claim, so two workers cannot each take a full max_parallel.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"funder_pool:{category}",))
        await conn.execute(RECOVER, {"category": category})
        free = (await (await conn.execute(FREE, {"category": category})).fetchone())["free"]
        free = free if limit is None else min(free, limit)
        if free <= 0:
            return []
        return await (await conn.execute(CLAIM, {"category": category, "worker": worker, "free": free})).fetchall()


async def start_run(conn: Any, row: dict[str, Any]) -> int:
    run = await (await conn.execute(
        "INSERT INTO ingest_runs (requested_sources, subjects, notes) VALUES ('{funder_pool}', %s, %s) RETURNING id",
        ([row["name"]], f"funder_pool {row['pool_funder_id']}"))).fetchone()
    await conn.execute("UPDATE funder_pool SET last_run_id = %s WHERE id = %s", (run["id"], row["id"]))
    return run["id"]


async def finish(conn: Any, row: dict[str, Any], status: str, *, funder_id: int | None = None,
                 cin: str | None = None, error: str | None = None, refund: bool = False) -> None:
    """End this claim and its run, unless lock recovery took it back. funder_id and cin only fill in, never clear;
    refund gives the attempt back, since a shutdown is not a failure."""
    completed = status in ("done", "skipped")
    ended = await (await conn.execute(
        "UPDATE funder_pool SET ingest_status = %s, funder_id = coalesce(%s, funder_id), cin = coalesce(%s, cin), "
        "last_error = %s, last_completed_at = CASE WHEN %s THEN now() ELSE last_completed_at END, "
        "attempts = attempts - %s, locked_at = NULL, locked_by = NULL, updated_at = now() "
        "WHERE id = %s AND locked_by = %s AND attempts = %s RETURNING last_run_id",
        (status, funder_id, cin, error, completed, int(refund), row["id"], row["locked_by"], row["attempts"]),
    )).fetchone()
    if not ended:
        return
    await conn.execute(
        "UPDATE ingest_runs SET status = %s, finished_at = now(), notes = coalesce(notes, '') || %s "
        "WHERE id = %s AND status = 'running'",
        ("failed" if status in ("pending", "failed") else "finished", f" · {status}", ended["last_run_id"]))


async def fail(conn: Any, row: dict[str, Any], error: str) -> str:
    """An attempt that raised: back to pending, or failed once it has used max_attempts. Returns the new status."""
    limit = await (await conn.execute(
        "SELECT max_attempts FROM funder_ingest_settings WHERE category = %s", (row["category"],))).fetchone()
    status = "failed" if row["attempts"] >= (limit["max_attempts"] if limit else 3) else "pending"
    await finish(conn, row, status, error=error[:1000])
    return status

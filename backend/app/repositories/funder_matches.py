"""Saved Funder Match runs. Run as the caller, so RLS decides whose rows are read and written."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

# The first key of pg_advisory_xact_lock's two-key form, so an org's run lock never meets another lock on its id.
RUN_LOCK = 4104


# The caller's first organisation by name, as /api/me lists them; used when a route is given no org.
FIRST_ORG = "(SELECT x.id FROM orgs x WHERE x.id IN (SELECT app.my_org_ids()) ORDER BY x.name LIMIT 1)"


async def find_org(pool: Any, slug_or_id: str) -> dict | None:
    """The org, whether the caller may read its runs and run one; None when the caller cannot see it."""
    async with pool.connection() as conn:
        return await _find_org(conn, slug_or_id)


async def _find_org(conn: Any, slug_or_id: str | None) -> dict | None:
    cur = await conn.execute(
        f"""SELECT o.id, o.slug, o.name,
                   (o.id IN (SELECT app.my_org_ids()) OR app.is_staff()) AS may_read,
                   (o.id IN (SELECT app.my_match_org_ids()) OR app.is_staff()) AS may_run
            FROM orgs o
            WHERE o.slug = %(v)s OR o.id::text = %(v)s OR (%(v)s::text IS NULL AND o.id = {FIRST_ORG})""",
        {"v": slug_or_id},
    )
    return await cur.fetchone()


async def read_latest(pool: Any, slug_or_id: str | None) -> tuple[dict | None, dict | None, list[dict]]:
    """The org, its latest run and that run's rows, in one transaction; stops early when there is nothing to read."""
    async with pool.connection() as conn:
        found = await _find_org(conn, slug_or_id)
        if found is None or not found["may_read"]:
            return found, None, []
        run = await _latest_run(conn, found["id"])
        rows = await _list_matches(conn, run["run_id"], run["prev_run_id"]) if run else []
        return found, run, rows


async def insert_run(pool: Any, org_id: int, run_id: UUID, run_by: UUID | None, rubric_version: str,
                     rows: list[dict]) -> dict:
    """Every row of one run in one transaction, one run per org at a time; run_at is the transaction's now()."""
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (RUN_LOCK, org_id))
        run_at = (await (await conn.execute("SELECT now() AS t")).fetchone())["t"]
        for r in rows:
            cur = await conn.execute(
                """INSERT INTO funder_matches (run_id, org_id, funder_id, run_at, run_by, rubric_version, score, card)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (run_id, org_id, r["funder_id"], run_at, run_by, rubric_version, r["score"], Jsonb(r["card"])),
            )
            match_id = (await cur.fetchone())["id"]
            await conn.execute(
                "INSERT INTO funder_match_details (match_id, detail) VALUES (%s, %s)", (match_id, Jsonb(r["detail"]))
            )
    return {"run_id": run_id, "run_at": run_at}


async def _latest_run(conn: Any, org_id: int) -> dict | None:
    """The org's latest run, the one before it, and how many runs came earlier."""
    runs = await (await conn.execute(
        """SELECT run_id, max(run_at) AS run_at, max(rubric_version) AS rubric_version, count(*) AS funders_checked
           FROM funder_matches WHERE org_id = %s GROUP BY run_id ORDER BY run_at DESC""",
        (org_id,),
    )).fetchall()
    if not runs:
        return None
    return {**runs[0], "earlier_runs": len(runs) - 1, "prev_run_id": runs[1]["run_id"] if len(runs) > 1 else None}


async def _list_matches(conn: Any, run_id: UUID, prev_run_id: UUID | None) -> list[dict]:
    """One run's rows with each funder, and its score in the run before; NULL scores last."""
    return await (await conn.execute(
        """SELECT m.id, m.score, m.card, p.score AS prev_score,
                  f.id AS funder_id, f.slug AS funder_slug, f.name AS funder_name, f.funder_type
           FROM funder_matches m
           JOIN funders f ON f.id = m.funder_id
           LEFT JOIN funder_matches p ON p.run_id = %s AND p.funder_id = m.funder_id
           WHERE m.run_id = %s
           ORDER BY m.score DESC NULLS LAST, f.name""",
        (prev_run_id, run_id),
    )).fetchall()


async def get_detail(pool: Any, match_id: int) -> dict | None:
    """One match's full reasoning; None when it does not exist or RLS hides it."""
    async with pool.connection() as conn:
        return await (await conn.execute(
            """SELECT m.id, m.run_at, m.rubric_version, d.detail
               FROM funder_matches m JOIN funder_match_details d ON d.match_id = m.id WHERE m.id = %s""",
            (match_id,),
        )).fetchone()

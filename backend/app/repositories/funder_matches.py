"""Saved Funder Match runs. Run as the caller, so RLS decides whose rows are read and written."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

# The first key of pg_advisory_xact_lock's two-key form, so an org's run lock never meets another lock on its id.
RUN_LOCK = 4104


async def find_org(pool: Any, slug_or_id: str) -> dict | None:
    """The org and whether the caller may run a match for it; None when the caller cannot see it."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT o.id, o.slug, o.name,
                      (o.id IN (SELECT app.my_match_org_ids()) OR app.is_staff()) AS may_run
               FROM orgs o WHERE o.slug = %(v)s OR o.id::text = %(v)s""",
            {"v": slug_or_id},
        )
        return await cur.fetchone()


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

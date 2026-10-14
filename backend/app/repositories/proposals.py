"""Proposals, run as the caller: RLS decides who reads (the org's people, staff) and who writes (admins,
stewards, staff). Every change to `work` goes through `save`, which locks the row and calls work.apply.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb

from app.proposals.work import Applied

_COLUMNS = """
  p.id, p.title, p.created_at, p.updated_at, p.summary, p.thread_id,
  p.work -> 'match' ->> 'score' AS fit_score,
  json_build_object('id', o.id, 'slug', o.slug, 'name', o.name) AS org,
  json_build_object('id', f.id, 'slug', f.slug, 'name', f.name) AS funder,
  (p.org_id IN (SELECT app.my_match_org_ids()) OR app.is_staff()) AS can_edit
"""
_FROM = "FROM proposals p JOIN orgs o ON o.id = p.org_id JOIN funders f ON f.id = p.funder_id"


async def list_proposals(pool: Any, *, org_id: int | None, funder_id: int | None) -> list[dict]:
    """Every proposal the caller may read, newest first; the list never reads `work`."""
    async with pool.connection() as conn:
        return await (await conn.execute(
            f"""SELECT {_COLUMNS} {_FROM}
                WHERE (%(org)s::bigint IS NULL OR p.org_id = %(org)s)
                  AND (%(funder)s::bigint IS NULL OR p.funder_id = %(funder)s)
                ORDER BY p.updated_at DESC, p.id DESC""",
            {"org": org_id, "funder": funder_id},
        )).fetchall()


async def get(pool: Any, proposal_id: int) -> dict | None:
    async with pool.connection() as conn:
        return await (await conn.execute(
            f"SELECT {_COLUMNS}, p.work {_FROM} WHERE p.id = %s", (proposal_id,)
        )).fetchone()


async def match_for(pool: Any, org_id: int, funder_id: int) -> dict | None:
    """This funder's row in the org's latest saved run, with the funder and its full reasoning."""
    async with pool.connection() as conn:
        return await (await conn.execute(
            """WITH latest AS (
                 SELECT run_id FROM funder_matches WHERE org_id = %(org)s ORDER BY run_at DESC LIMIT 1
               )
               SELECT m.id, m.score, m.run_at, d.detail,
                      f.id AS funder_id, f.name AS funder_name, f.funder_type, f.section_135_bound
               FROM funder_matches m
               JOIN latest l ON l.run_id = m.run_id
               JOIN funder_match_details d ON d.match_id = m.id
               JOIN funders f ON f.id = m.funder_id
               WHERE m.funder_id = %(funder)s""",
            {"org": org_id, "funder": funder_id},
        )).fetchone()


async def funder_form(pool: Any, funder_id: int) -> dict | None:
    """The newest proposal form Sangam holds for this funder."""
    async with pool.connection() as conn:
        return await (await conn.execute(
            """SELECT id, source_url, fetched_at FROM documents
               WHERE funder_id = %s AND doc_type = 'proposal_template'
               ORDER BY fetched_at DESC NULLS LAST, id DESC LIMIT 1""",
            (funder_id,),
        )).fetchone()


async def me(pool: Any) -> dict:
    """The caller as a log entry names them."""
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT id, coalesce(display_name, split_part(email, '@', 1)) AS name FROM users WHERE id = app.user_id()"
        )).fetchone()
    return {"id": str(row["id"]), "name": row["name"]} if row else {"id": None, "name": "Someone"}


async def create(pool: Any, *, org_id: int, funder_id: int, title: str, work: dict, summary: dict,
                 created_by: Any) -> int:
    async with pool.connection() as conn:
        return (await (await conn.execute(
            """INSERT INTO proposals (org_id, funder_id, title, work, summary, created_by)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (org_id, funder_id, title, Jsonb(work), Jsonb(summary), created_by),
        )).fetchone())["id"]


async def save(pool: Any, proposal_id: int, change: Callable[[dict, str], Applied]) -> Applied | None:
    """Lock the row, apply `change` to its work, write it back. None when the caller may not write it."""
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT work, title FROM proposals WHERE id = %s FOR UPDATE", (proposal_id,)
        )).fetchone()
        if row is None:
            return None
        applied = change(row["work"], row["title"])
        await conn.execute(
            """UPDATE proposals SET work = %s, summary = %s, title = coalesce(%s, title), updated_at = now()
               WHERE id = %s""",
            (Jsonb(applied.work), Jsonb(applied.summary), applied.title, proposal_id),
        )
    return applied


# The agent's side, on the owner pool: chat access and require_edit decide who gets here, not RLS.
_CHAT = re.compile(r"^proposal-(\d+)-([0-9a-f-]{36})$")


def chat_thread(proposal_id: int, user_id: Any) -> str:
    """Each person's own chat about a proposal; teammates never share one."""
    return f"proposal-{proposal_id}-{user_id}"


def parse_chat_thread(thread_id: str) -> tuple[int, str] | None:
    m = _CHAT.match(thread_id or "")
    return (int(m.group(1)), m.group(2)) if m else None


async def org_of(pool: Any, proposal_id: int) -> int | None:
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT org_id FROM proposals WHERE id = %s", (proposal_id,))).fetchone()
    return row["org_id"] if row else None


async def load(pool: Any, proposal_id: int) -> dict | None:
    """The proposal with its org's and funder's names, for the agent's context."""
    async with pool.connection() as conn:
        return await (await conn.execute(
            """SELECT p.id, p.title, p.org_id, p.funder_id, p.thread_id, p.work,
                      o.name AS org_name, f.name AS funder_name
               FROM proposals p JOIN orgs o ON o.id = p.org_id JOIN funders f ON f.id = p.funder_id
               WHERE p.id = %s""",
            (proposal_id,),
        )).fetchone()


async def user_name(pool: Any, user_id: Any) -> dict:
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT id, coalesce(display_name, split_part(email, '@', 1)) AS name FROM users WHERE id = %s",
            (user_id,),
        )).fetchone()
    return {"id": str(row["id"]), "name": row["name"]} if row else {"id": None, "name": "Someone"}

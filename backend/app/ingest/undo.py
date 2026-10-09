"""Undoing an Import save, and deleting research that was never saved. Staff only; the routes check."""

from __future__ import annotations

from typing import Any

from psycopg import errors, sql

# The tables 0041's trigger logs. A name read back from catalog_writes is checked against this before use.
LOGGED = frozenset({
    "funders", "funder_csr_years", "funder_activity", "funder_locations", "funder_tags", "programs", "metrics",
    "contacts", "rfps", "rfp_locations", "rfp_tags", "documents", "orgs", "org_identifiers", "org_financials",
    "org_locations",
})
# Research rows point at the entity a save created; undoing the creation unlinks them first.
_RESOLVED = {"funders": "resolved_funder_id", "orgs": "resolved_org_id"}


class UndoRefused(Exception):
    """A row the save wrote has changed since, or is now needed by something else: nothing is undone."""


async def start(conn: Any, research_id: int | None, slug: str, user_id: Any) -> int:
    """Open a promotion and turn on the write log for the rest of this transaction."""
    row = await (await conn.execute(
        "INSERT INTO promotions (research_id, slug, promoted_by) VALUES (%s, %s, %s) RETURNING id",
        (research_id, slug, user_id),
    )).fetchone()
    await conn.execute("SELECT set_config('sangam.promotion_id', %s, true)", (str(row["id"]),))
    return row["id"]


async def finish(conn: Any, promotion_id: int) -> bool:
    """Stop logging; a save that wrote nothing leaves no promotion behind. True when it wrote something."""
    await conn.execute("SELECT set_config('sangam.promotion_id', '', true)")
    wrote = await (await conn.execute(
        "SELECT EXISTS (SELECT 1 FROM catalog_writes WHERE promotion_id = %s) AS wrote", (promotion_id,)
    )).fetchone()
    if not wrote["wrote"]:
        await conn.execute("DELETE FROM promotions WHERE id = %s", (promotion_id,))
    return bool(wrote["wrote"])


async def _columns(conn: Any, table: str) -> list[str]:
    rows = await (await conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s "
        "AND is_generated = 'NEVER' AND is_identity = 'NO' ORDER BY ordinal_position",
        (table,),
    )).fetchall()
    return [r["column_name"] for r in rows]


def _same(table: str, row: dict[str, Any], write_id: int) -> tuple[sql.Composable, list[Any]]:
    """WHERE the row is exactly as the save left it, by id when the table has one.
    Compared with the logged jsonb in SQL, since a round trip through Python turns numerics into floats."""
    t = sql.Identifier(table)
    where = sql.SQL("to_jsonb({t}.*) = (SELECT new_row FROM catalog_writes WHERE id = %s)").format(t=t)
    params: list[Any] = [write_id]
    if "id" in row:
        where = sql.SQL("{t}.id = %s AND ").format(t=t) + where
        params.insert(0, row["id"])
    return where, params


async def undo(conn: Any, promotion_id: int, user_id: Any) -> dict[str, Any]:
    """Reverse one save in one transaction, newest write first. Raises UndoRefused and changes nothing on a conflict."""
    promo = await (await conn.execute(
        "SELECT id, research_id, slug, undone_at FROM promotions WHERE id = %s FOR UPDATE", (promotion_id,)
    )).fetchone()
    if promo is None:
        raise LookupError(promotion_id)
    if promo["undone_at"] is not None:
        raise UndoRefused("this save was already undone")
    writes = await (await conn.execute(
        "SELECT id, table_name, action, old_row, new_row FROM catalog_writes WHERE promotion_id = %s ORDER BY id DESC",
        (promotion_id,),
    )).fetchall()
    counts = {"removed": 0, "restored": 0}
    async with conn.transaction():
        for w in writes:
            table = w["table_name"]
            if table not in LOGGED:
                raise UndoRefused(f"{table} is not a catalog table")
            where, params = _same(table, w["new_row"], w["id"])
            if w["action"] == "insert":
                if table in _RESOLVED:
                    await conn.execute(
                        sql.SQL("UPDATE entity_research SET {c} = NULL WHERE {c} = %s").format(
                            c=sql.Identifier(_RESOLVED[table])),
                        (w["new_row"]["id"],),
                    )
                query = sql.SQL("DELETE FROM {t} WHERE ").format(t=sql.Identifier(table)) + where
                key = "removed"
            else:
                cols = [c for c in await _columns(conn, table) if c in w["old_row"]]
                query = sql.SQL("UPDATE {t} SET ({cols}) = (SELECT {cols} FROM jsonb_populate_record(NULL::{t}, "
                                "(SELECT old_row FROM catalog_writes WHERE id = %s))) WHERE ").format(
                    t=sql.Identifier(table), cols=sql.SQL(", ").join(map(sql.Identifier, cols))) + where
                params = [w["id"], *params]
                key = "restored"
            try:
                cur = await conn.execute(query, params)
            except errors.IntegrityError as exc:  # a row something else now points at
                raise UndoRefused(f"a {table} row is now used elsewhere ({type(exc).__name__})") from exc
            if cur.rowcount != 1:
                raise UndoRefused(f"a {table} row has changed since this save")
            counts[key] += 1
        await conn.execute("UPDATE promotions SET undone_at = now(), undone_by = %s WHERE id = %s",
                           (user_id, promotion_id))
        # The research reads as unsaved again once no save of it stands.
        await conn.execute(
            "UPDATE entity_research SET saved = NULL, saved_at = NULL WHERE id = %s AND NOT EXISTS "
            "(SELECT 1 FROM promotions WHERE research_id = %s AND undone_at IS NULL)",
            (promo["research_id"], promo["research_id"]),
        )
    return {"promotion_id": promotion_id, "slug": promo["slug"], **counts}


async def delete_research(conn: Any, slug: str) -> int | None:
    """Delete every research row for a slug, its vault findings too. None when a save of it still stands."""
    standing = await (await conn.execute(
        "SELECT EXISTS (SELECT 1 FROM promotions WHERE slug = %s AND undone_at IS NULL) AS standing", (slug,)
    )).fetchone()
    if standing["standing"]:
        return None
    cur = await conn.execute("DELETE FROM entity_research WHERE slug = %s", (slug,))
    await conn.execute("DELETE FROM vault_research WHERE slug = %s", (slug,))
    return cur.rowcount

"""Partner lines grouped as a profile lists them: a funder's partners, or an org's funders, a page of groups at a time.

The key groups a funder's lines the way the page always has: the partner org when one is linked, else its folded name."""

from __future__ import annotations

from typing import Any, Literal

from app.repositories import keyset
from app.repositories.partner_lines import FY_IS_DATED
from app.repositories.public_sql import public_text, source

Side = Literal["funder", "org"]

# The year a line is shown under; undated lines sort last.
_YEAR = f"""CASE WHEN {FY_IS_DATED} THEN a.fiscal_year
                 WHEN a.start_date IS NOT NULL THEN 'FY' || extract(year FROM a.start_date)::int
                 ELSE '' END"""

GROUP_KEY = {
    "funder": "coalesce('o' || a.partner_org_id, 'n' || lower(btrim(a.partner_name)))",
    "org": "a.funder_id::text",
}
_NAME = {"funder": "coalesce(o.name, a.partner_name)", "org": "f.name"}
_OWNER = {"funder": "a.funder_id", "org": "a.partner_org_id"}

_LINES = """
SELECT a.id, a.funder_id, f.slug AS funder_slug, f.name AS funder_name, a.fiscal_year,
       a.partner_name, o.id AS partner_org_id, o.slug AS partner_org_slug, o.name AS partner_org_name,
       a.project_name, a.program_id, p.name AS program_name, a.amount, a.start_date, a.end_date,
       a.relationship_status, {notes} AS notes, {source}, a.fetched_at,
       {dated} AS fy_is_dated, {year} AS yr, {key} AS gkey, {name} AS gname
FROM funder_activity a
JOIN funders f ON f.id = a.funder_id
LEFT JOIN orgs o ON o.id = a.partner_org_id
LEFT JOIN programs p ON p.id = a.program_id
WHERE a.kind = 'partner' AND a.is_public AND {owner} = %(id)s
"""


def _lines(side: Side) -> str:
    return _LINES.format(notes=public_text("a.notes"), source=source("a"), dated=FY_IS_DATED, year=_YEAR,
                         key=GROUP_KEY[side], name=_NAME[side], owner=_OWNER[side])


def decode_cursor(cursor: str | None) -> int:
    """A page's offset; a cursor of the wrong shape is a ValueError (400), never a database error."""
    if not cursor:
        return 0
    values = keyset.decode(cursor)
    if len(values) != 1 or not isinstance(values[0], int) or values[0] < 0:
        raise ValueError("bad cursor")
    return values[0]


async def group_page(conn, side: Side, entity_id: int, *, offset: int, limit: int) -> dict:
    """One page of groups, newest latest-year first, each with all its lines; totals cover every group."""
    lines_sql = _lines(side)
    groups = await (await conn.execute(f"""
        WITH lines AS ({lines_sql}),
        g AS (SELECT gkey, min(gname) AS gname, max(yr) AS latest, min(partner_org_slug) AS org_slug,
                     min(funder_slug) AS funder_slug FROM lines GROUP BY gkey)
        SELECT g.*, count(*) OVER () AS total FROM g
        ORDER BY latest DESC, lower(gname), gkey
        OFFSET %(off)s LIMIT %(lim)s""", {"id": entity_id, "off": offset, "lim": limit + 1})).fetchall()
    totals = await (await conn.execute(f"""
        WITH lines AS ({lines_sql})
        SELECT count(DISTINCT gkey) AS total, count(DISTINCT partner_org_id) AS in_registry,
               coalesce(bool_or(amount IS NOT NULL), false) AS has_amounts FROM lines""",
        {"id": entity_id})).fetchone()
    more = len(groups) > limit
    groups = groups[:limit]
    keys = [g["gkey"] for g in groups]
    rows = await (await conn.execute(
        f"SELECT * FROM ({lines_sql}) l WHERE gkey = ANY(%(keys)s) ORDER BY yr DESC, id",
        {"id": entity_id, "keys": keys})).fetchall() if keys else []
    return {
        "groups": [{"key": g["gkey"], "name": g["gname"], "org_slug": g["org_slug"] if side == "funder" else None,
                    "funder_slug": g["funder_slug"] if side == "org" else None,
                    "lines": [r for r in rows if r["gkey"] == g["gkey"]]} for g in groups],
        "total": totals["total"], "in_registry": totals["in_registry"] if side == "funder" else 0,
        "has_amounts": totals["has_amounts"],
        "next_cursor": keyset.encode((offset + limit,)) if more else None,
    }


async def entity_groups(pool: Any, side: Side, slug_or_id: str, *, cursor: str | None, limit: int) -> dict | None:
    """The groups of a funder (side 'funder') or an org (side 'org') named by slug or id; None when unknown."""
    offset = decode_cursor(cursor)
    table = "funders" if side == "funder" else "orgs"
    async with pool.connection() as conn:
        row = await (await conn.execute(
            f"SELECT id FROM {table} WHERE slug = %(v)s OR id::text = %(v)s", {"v": slug_or_id})).fetchone()
        if row is None:
            return None
        return await group_page(conn, side, row["id"], offset=offset, limit=limit)

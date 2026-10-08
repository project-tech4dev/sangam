"""The two sides of a funder match, read in fixed queries. rules.py judges them; nothing here decides."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from psycopg_pool import AsyncConnectionPool

from app.agent.rules import FunderProfile, Identifier, Location, OrgProfile, Places, Program

# Tag kinds a theme is compared on; meta->>'maps_to' carries a sector's Schedule VII slug.
SECTOR, CSR = "sector", "csr_sector"
# The eligibility document's sections a person must review; the statutory ones are the credential checks.
BAR_SECTIONS = ("## Its own bar", "## Disqualifiers")


async def _rows(conn: Any, sql: str, params: Any = None) -> list[dict]:
    return await (await conn.execute(sql, params)).fetchall()


async def _read_only(conn: Any, timeout_ms: int) -> None:
    # Same guards as the SQL tools: the pool is shared with the checkpointer, which writes.
    await conn.execute("SET TRANSACTION READ ONLY")
    await conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")


def _tag_sets(rows: list[dict]) -> tuple[set[str], set[str]]:
    sectors, csr = set(), set()
    for r in rows:
        if r["kind"] == SECTOR:
            sectors.add(r["slug"])
            if r["maps_to"]:
                csr.add(r["maps_to"])
        elif r["kind"] == CSR:
            csr.add(r["slug"])
    return sectors, csr


async def load(
    pool: AsyncConnectionPool, org_id: int, funder_ids: list[int] | None, *, timeout_ms: int = 5_000
) -> tuple[OrgProfile | None, list[FunderProfile], Places]:
    """The organisation, the funders (all when funder_ids is None) and the locations table."""
    async with pool.connection() as conn, conn.transaction():
        await _read_only(conn, timeout_ms)
        org = await _org(conn, org_id)
        funders = await _funders(conn, funder_ids)
        places = Places([Location(**r) for r in await _rows(conn, "SELECT id, kind, name, parent_id FROM locations")])
    return org, funders, places


async def _org(conn: Any, org_id: int) -> OrgProfile | None:
    head = await _rows(conn, "SELECT id, name FROM orgs WHERE id = %s", (org_id,))
    if not head:
        return None
    org = OrgProfile(id=head[0]["id"], name=head[0]["name"])
    org.location_ids = {
        r["location_id"] for r in await _rows(conn, "SELECT location_id FROM org_locations WHERE org_id = %s", (org_id,))
    }
    org.sector_tags, org.csr_slugs = _tag_sets(await _rows(conn, """
        SELECT t.slug, t.kind, t.meta->>'maps_to' AS maps_to
        FROM org_tags ot JOIN tags t ON t.id = ot.tag_id WHERE ot.org_id = %s""", (org_id,)))

    programs: dict[int, dict] = {}
    tags: dict[int, list[dict]] = defaultdict(list)
    for r in await _rows(conn, """
        SELECT p.id, p.name, p.status, p.end_date, t.slug, t.kind, t.meta->>'maps_to' AS maps_to
        FROM programs p
        LEFT JOIN program_tags pt ON pt.program_id = p.id
        LEFT JOIN tags t ON t.id = pt.tag_id
        WHERE p.org_id = %s
        ORDER BY p.id""", (org_id,)):
        programs.setdefault(r["id"], r)
        if r["slug"]:
            tags[r["id"]].append(r)
    for pid, r in programs.items():
        sectors, csr = _tag_sets(tags[pid])
        org.programs.append(Program(pid, r["name"], r["status"], r["end_date"], frozenset(sectors | csr)))

    for r in await _rows(conn, """
        SELECT id_type, status, id_value, is_current, valid_until, evidence, source_type
        FROM org_identifiers WHERE org_id = %s ORDER BY id""", (org_id,)):
        org.identifiers.setdefault(r.pop("id_type"), []).append(Identifier(**r))
    org.financials = [
        (r["fiscal_year"], r["is_audited"]) for r in await _rows(conn, """
            SELECT fiscal_year, is_audited FROM org_financials
            WHERE org_id = %s ORDER BY fiscal_year DESC""", (org_id,))
    ]
    org.doc_types = [
        r["doc_type"] for r in await _rows(conn, "SELECT doc_type FROM documents WHERE org_id = %s", (org_id,))
        if r["doc_type"]
    ]
    org.office_bearers = (await _rows(conn, """
        SELECT count(*) AS n FROM contacts WHERE org_id = %s AND kind = 'office_bearer'""", (org_id,)))[0]["n"]
    # A grant to the organisation is a funder's partner line.
    org.partner_lines = [
        (r["id"], r["relationship_status"], r["end_date"]) for r in await _rows(conn, """
            SELECT id, relationship_status, end_date FROM funder_activity
            WHERE kind = 'partner' AND partner_org_id = %s ORDER BY id""", (org_id,))
    ]
    return org


async def _funders(conn: Any, funder_ids: list[int] | None) -> list[FunderProfile]:
    # NULL means every funder: one plan for both, so a shortlist costs the same five queries as one pair.
    ids = funder_ids
    where = "(%(ids)s::bigint[] IS NULL OR {col} = ANY(%(ids)s))"
    params = {"ids": ids}
    funders = {
        r["id"]: FunderProfile(r["id"], r["name"], r["funder_type"], r["section_135_bound"])
        for r in await _rows(conn, f"""
            SELECT id, name, funder_type, section_135_bound FROM funders
            WHERE {where.format(col='id')} ORDER BY id""", params)
    }
    for r in await _rows(conn, f"""
        SELECT funder_id, location_id, role FROM funder_locations WHERE {where.format(col='funder_id')}
        UNION ALL
        SELECT funder_id, place, 'footprint'
        FROM funder_activity, LATERAL (VALUES (location_id), (state_location_id)) AS p(place)
        WHERE kind = 'footprint' AND place IS NOT NULL AND {where.format(col='funder_id')}""", params):
        f = funders.get(r["funder_id"])
        if f is None:
            continue
        # Where it is registered is not where it gives.
        (f.registered_ids if r["role"] == "registered" else f.location_ids).add(r["location_id"])

    tag_rows: dict[int, list[dict]] = defaultdict(list)
    for r in await _rows(conn, f"""
        SELECT ft.funder_id, t.slug, t.kind, t.meta->>'maps_to' AS maps_to
        FROM funder_tags ft JOIN tags t ON t.id = ft.tag_id
        WHERE {where.format(col='ft.funder_id')}""", params):
        tag_rows[r["funder_id"]].append(r)
    for fid, rows in tag_rows.items():
        if fid in funders:
            funders[fid].sector_tags, funders[fid].csr_slugs = _tag_sets(rows)

    for r in await _rows(conn, f"""
        SELECT id, funder_id, content_md FROM documents
        WHERE doc_type = 'funder_eligibility' AND {where.format(col='funder_id')} ORDER BY id""", params):
        if r["funder_id"] in funders:
            funders[r["funder_id"]].bars += [(r["id"], text) for text in _bars(r["content_md"] or "")]
    return list(funders.values())


def _bars(content_md: str) -> list[str]:
    """The criteria under the bar headings, one per paragraph, as EligibilityGuidelineRecord writes them."""
    bars, keep = [], False
    for para in (p.strip() for p in content_md.split("\n\n")):
        if para.startswith("## "):
            keep = para in BAR_SECTIONS
        elif para and keep:
            bars.append(para)
    return bars

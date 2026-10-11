"""The two sides of a funder match, read in fixed queries. rules.py judges them; nothing here decides."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from psycopg_pool import AsyncConnectionPool

from app.matching.rules import (
    FunderProfile,
    Identifier,
    Location,
    OrgProfile,
    PartnerLine,
    Places,
    Program,
    Themes,
)

# Darpan's `sector` tags are left in place but never compared: the theme taxonomy replaced them.
THEME_KINDS = ("domain", "theme", "sub_theme", "csr_sector")
# The eligibility document's sections a person must review; the statutory ones are the credential checks.
BAR_SECTIONS = ("## Its own bar", "## Disqualifiers")


async def _rows(conn: Any, sql: str, params: Any = None) -> list[dict]:
    return await (await conn.execute(sql, params)).fetchall()


async def _read_only(conn: Any, timeout_ms: int) -> None:
    # Same guards as the SQL tools: the pool is shared with the checkpointer, which writes.
    await conn.execute("SET TRANSACTION READ ONLY")
    await conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")


class Taxonomy:
    """The theme tree and each sub-theme's Schedule VII clauses, so a tag brings its ancestors."""

    def __init__(self, tags: list[dict], clause_links: list[dict]):
        self.by_id = {t["id"]: t for t in tags}
        self.clauses: dict[int, set[str]] = defaultdict(set)
        for link in clause_links:
            self.clauses[link["tag_id"]].add(link["clause"])

    def themes(self, tag_ids: Any) -> Themes:
        themes, clauses, domains = set(), set(), set()
        for tid in tag_ids:
            seen: set[int] = set()
            while (t := self.by_id.get(tid)) is not None and tid not in seen:
                seen.add(tid)
                {"sub_theme": themes, "theme": themes, "csr_sector": clauses, "domain": domains}[t["kind"]].add(t["slug"])
                clauses |= self.clauses[tid]
                tid = t["parent_id"]
        return Themes(frozenset(themes), frozenset(clauses), frozenset(domains))

    def labels(self) -> dict[str, str]:
        return {t["slug"]: t["label"] for t in self.by_id.values()}


async def _taxonomy(conn: Any) -> Taxonomy:
    tags = await _rows(conn, "SELECT id, slug, label, kind, parent_id FROM tags WHERE kind = ANY(%s)",
                       (list(THEME_KINDS),))
    links = await _rows(conn, """
        SELECT l.tag_id, c.slug AS clause FROM tag_links l
        JOIN tags c ON c.id = l.linked_tag_id AND c.kind = 'csr_sector'""")
    return Taxonomy(tags, links)


def _split(rows: list[dict], tax: Taxonomy) -> tuple[Themes, set[str], dict[str, str]]:
    """A side's tag rows as its themes, its population slugs and the population labels."""
    population = {r["slug"]: r["label"] for r in rows if r["kind"] == "population"}
    return tax.themes(r["tag_id"] for r in rows if r["kind"] in THEME_KINDS), set(population), population


async def load(
    pool: AsyncConnectionPool, org_id: int, funder_ids: list[int] | None, *, timeout_ms: int = 5_000
) -> tuple[OrgProfile | None, list[FunderProfile], Places]:
    """The organisation, the funders (all when funder_ids is None) and the locations table."""
    async with pool.connection() as conn, conn.transaction():
        await _read_only(conn, timeout_ms)
        tax = await _taxonomy(conn)
        org = await _org(conn, org_id, tax)
        funders = await _funders(conn, funder_ids, tax)
        places = Places([Location(**r) for r in await _rows(conn, "SELECT id, kind, name, parent_id FROM locations")])
    return org, funders, places


async def _org(conn: Any, org_id: int, tax: Taxonomy) -> OrgProfile | None:
    head = await _rows(conn, "SELECT id, name FROM orgs WHERE id = %s", (org_id,))
    if not head:
        return None
    org = OrgProfile(id=head[0]["id"], name=head[0]["name"])
    org.location_ids = {
        r["location_id"] for r in await _rows(conn, "SELECT location_id FROM org_locations WHERE org_id = %s", (org_id,))
    }
    org.themes, org.population, pop_labels = _split(await _rows(conn, """
        SELECT t.id AS tag_id, t.slug, t.label, t.kind
        FROM org_tags ot JOIN tags t ON t.id = ot.tag_id WHERE ot.org_id = %s""", (org_id,)), tax)

    programs: dict[int, dict] = {}
    tags: dict[int, list[dict]] = defaultdict(list)
    for r in await _rows(conn, """
        SELECT p.id, p.name, t.id AS tag_id, t.slug, t.label, t.kind
        FROM programs p
        LEFT JOIN program_tags pt ON pt.program_id = p.id
        LEFT JOIN tags t ON t.id = pt.tag_id
        WHERE p.org_id = %s
        ORDER BY p.id""", (org_id,)):
        programs.setdefault(r["id"], r)
        if r["slug"]:
            tags[r["id"]].append(r)
    for pid, r in programs.items():
        themes, population, labels = _split(tags[pid], tax)
        org.programs.append(Program(pid, r["name"], themes))
        org.themes |= themes
        org.population |= population
        pop_labels |= labels
    org.labels = tax.labels() | pop_labels

    for r in await _rows(conn, """
        SELECT id_type, status, id_value, is_current, valid_until, evidence, source_type
        FROM org_identifiers WHERE org_id = %s ORDER BY id""", (org_id,)):
        org.identifiers.setdefault(r.pop("id_type"), []).append(Identifier(**r))
    org.financials = [
        (r["fiscal_year"], r["is_audited"]) for r in await _rows(conn, """
            SELECT fiscal_year, is_audited FROM org_financials
            WHERE org_id = %s ORDER BY fiscal_year DESC""", (org_id,))
    ]
    org.total_income = next((r["total_income"] for r in await _rows(conn, """
        SELECT total_income FROM org_financials
        WHERE org_id = %s AND total_income IS NOT NULL ORDER BY fiscal_year DESC LIMIT 1""", (org_id,))), None)
    org.doc_types = [
        r["doc_type"] for r in await _rows(conn, "SELECT doc_type FROM documents WHERE org_id = %s", (org_id,))
        if r["doc_type"]
    ]
    # A grant to the organisation is a funder's partner line.
    org.partner_lines = [
        PartnerLine(**r) for r in await _rows(conn, """
            SELECT id, funder_id, relationship_status FROM funder_activity
            WHERE partner_org_id = %s ORDER BY id""", (org_id,))
    ]
    return org


async def _funders(conn: Any, funder_ids: list[int] | None, tax: Taxonomy) -> list[FunderProfile]:
    # NULL means every funder: one plan for both, so a shortlist costs the same six queries as one pair.
    ids = funder_ids
    where = "(%(ids)s::bigint[] IS NULL OR {col} = ANY(%(ids)s))"
    params = {"ids": ids}
    funders = {
        r["id"]: FunderProfile(**r)
        for r in await _rows(conn, f"""
            SELECT id, name, funder_type, section_135_bound, grant_size_min, grant_size_max FROM funders
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

    # Its own tags, and what each activity line was classified under: a line says what it funds.
    tag_rows: dict[int, list[dict]] = defaultdict(list)
    for r in await _rows(conn, f"""
        SELECT ft.funder_id, t.id AS tag_id, t.slug, t.label, t.kind
        FROM funder_tags ft JOIN tags t ON t.id = ft.tag_id
        WHERE {where.format(col='ft.funder_id')}
        UNION
        SELECT a.funder_id, t.id, t.slug, t.label, t.kind
        FROM funder_activity a, LATERAL (VALUES (a.domain_tag_id), (a.theme_tag_id), (a.csr_sector_id)) AS c(tag_id)
        JOIN tags t ON t.id = c.tag_id
        WHERE {where.format(col='a.funder_id')}""", params):
        tag_rows[r["funder_id"]].append(r)
    labels = tax.labels()
    for fid, rows in tag_rows.items():
        if fid in funders:
            f = funders[fid]
            f.themes, f.population, pop_labels = _split(rows, tax)
            f.labels = labels | pop_labels

    for r in await _rows(conn, f"""
        SELECT id, funder_id, fiscal_year FROM funder_activity
        WHERE kind IN ('spend', 'programme') AND amount IS NOT NULL AND fiscal_year IS NOT NULL
          AND {where.format(col='funder_id')} ORDER BY id""", params):
        if r["funder_id"] in funders:
            funders[r["funder_id"]].spend.append((r["id"], r["fiscal_year"]))

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


async def may_run(pool: AsyncConnectionPool, user_id: Any, org_id: int) -> bool:
    """Staff, or an admin or steward of the org: the same people 0042 lets save a run."""
    if user_id is None:
        return False
    async with pool.connection() as conn:
        row = await (await conn.execute(
            """SELECT EXISTS (SELECT 1 FROM users WHERE id = %(u)s AND is_staff)
                   OR EXISTS (SELECT 1 FROM org_members WHERE user_id = %(u)s AND org_id = %(o)s
                              AND role IN ('admin', 'steward')) AS ok""",
            {"u": user_id, "o": org_id},
        )).fetchone()
    return bool(row["ok"])

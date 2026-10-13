"""Everything a registry profile shows from the catalog, as one typed result per page.

The entity and its catalog rows are read as the caller, so RLS decides whether the page exists; each query still
filters is_public itself, since a profile is public. Registrations, private-contact counts and research are read
on the owner pool with explicit rules, so every viewer gets the same page."""

from __future__ import annotations

from typing import Any

from app.repositories.news_stories import SOCIAL
from app.repositories.partner_groups import group_page
from app.repositories.public_sql import (
    IDENTIFIERS,
    OPEN_CALL,
    STATE_OF,
    entity_sdgs,
    entity_tags,
    is_private_url,
    public_name,
    public_text,
    public_url,
    research_match,
    source,
    story_counts,
)
from app.schemas.profiles import FunderFacts, OrgFacts

FIRST_PAGE = 20

_PARENT = "CASE WHEN p.id IS NOT NULL THEN jsonb_build_object('id', p.id, 'name', p.name, 'slug', p.slug) END"

_ORG = f"""
SELECT o.id, o.slug, o.name, o.legal_form, o.registration_date, o.registered_address,
       {public_url('o.website')} AS website, {public_text('o.description')} AS description, o.aliases,
       o.staff_count, {public_text('o.staff_count_note')} AS staff_count_note,
       dl.name AS district, sl.name AS state, {source('o')}, {_PARENT} AS parent
FROM orgs o
LEFT JOIN orgs p ON p.id = o.parent_id
LEFT JOIN locations dl ON dl.id = o.registered_location_id
LEFT JOIN locations sl ON sl.id = dl.parent_id
WHERE o.slug = %(v)s OR o.id::text = %(v)s
"""

_FUNDER = f"""
SELECT f.id, f.slug, f.name, f.funder_type, {public_url('f.website')} AS website,
       {public_text("f.profile->>'funding_trend'")} AS funding_trend, f.legal_form, f.founded_year,
       f.registered_address, rl.name AS registered_location, f.cin, f.section_135_bound, f.intake_mode,
       f.funds_external, f.typical_duration_months, f.grant_size_min, f.grant_size_max, f.aliases,
       {source('f')}, {_PARENT} AS parent
FROM funders f
LEFT JOIN funders p ON p.id = f.parent_id
LEFT JOIN locations rl ON rl.id = f.registered_location_id
WHERE f.slug = %(v)s OR f.id::text = %(v)s
"""

_PROGRAMS = f"""
SELECT id, name, kind, parent_id, {public_text('description')} AS description, status, start_date, end_date,
       {public_name('source_name', 'source_url')} AS source_name, {public_url('source_url')} AS source_url
FROM programs WHERE {{owner}} = %(id)s
ORDER BY parent_id NULLS FIRST, start_date DESC NULLS LAST, name
"""

_PROGRAM_TAGS = f"""
SELECT pt.program_id, tg.slug, tg.label, tg.kind, pt.role, {public_text('pt.note')} AS note,
       par.label AS parent_label
FROM program_tags pt JOIN tags tg ON tg.id = pt.tag_id LEFT JOIN tags par ON par.id = tg.parent_id
WHERE pt.program_id = ANY(%(pids)s)
ORDER BY pt.role, tg.label
"""

# A metric on a partner line is as public as the line.
_METRICS = f"""
SELECT m.id, m.name, m.value, m.target, m.unit, m.period, m.stage, m.method, m.program_id,
       l.name AS place, {source('m')}
FROM metrics m LEFT JOIN locations l ON l.id = m.location_id
WHERE (m.{{owner}} = %(id)s OR m.program_id IN (SELECT id FROM programs WHERE {{owner}} = %(id)s))
  AND (m.activity_id IS NULL
       OR EXISTS (SELECT 1 FROM funder_activity a WHERE a.id = m.activity_id AND a.is_public))
ORDER BY m.program_id NULLS LAST, m.sequence NULLS LAST, m.name
"""

# The same person read from two pages is two rows; the page shows them once.
_CONTACTS = f"""
SELECT DISTINCT ON (kind, name, coalesce(email, ''))
       id, name, role, kind, email, phone, {source('c')}
FROM contacts c WHERE {{owner}} = %(id)s AND is_public
ORDER BY kind, name, coalesce(email, ''), id
"""

# Eligibility has its own section on a funder page, so it is not listed again as a source.
_DOCUMENTS = f"""
SELECT d.id, d.title, d.doc_type, d.as_of, {source('d')}
FROM documents d
WHERE d.is_public AND d.doc_type IS DISTINCT FROM 'funder_eligibility'
  AND (d.{{owner}} = %(id)s
       OR EXISTS (SELECT 1 FROM document_links dl WHERE dl.document_id = d.id AND dl.{{owner}} = %(id)s))
ORDER BY d.as_of DESC NULLS LAST, d.title
"""

_DOCUMENT_LINKS = """
SELECT dl.document_id, dl.program_id, p.name AS program_name, dl.fiscal_year, dl.pages
FROM document_links dl LEFT JOIN programs p ON p.id = dl.program_id
WHERE dl.{owner} = %(id)s AND dl.document_id = ANY(%(dids)s)
ORDER BY dl.fiscal_year DESC NULLS LAST, p.name NULLS FIRST
"""

_PLACES = f"""
SELECT l.id AS location_id, l.kind, l.name, {STATE_OF} AS state, ol.role, {public_text('ol.note')} AS note,
       ol.program_id, p.name AS program_name, {source('ol')}
FROM org_locations ol
JOIN locations l ON l.id = ol.location_id
LEFT JOIN locations lp ON lp.id = l.parent_id
LEFT JOIN programs p ON p.id = ol.program_id
WHERE ol.org_id = %(id)s
ORDER BY 4 NULLS LAST, l.name
"""

_FINANCIALS = f"""
SELECT fiscal_year, total_income, program_spend, non_program_spend, foreign_contribution, foreign_unspent,
       is_audited, {source('x')}
FROM org_financials x WHERE org_id = %(id)s
ORDER BY fiscal_year DESC
"""

_SPEND = f"""
SELECT a.id, a.program_id, COALESCE(p.name, a.name_as_printed, a.project_name) AS program_name,
       a.fiscal_year, a.amount, {public_text('a.notes')} AS notes, {source('a')}
FROM funder_activity a LEFT JOIN programs p ON p.id = a.program_id
WHERE a.funder_id = %(id)s AND a.kind = 'programme' AND a.is_public
ORDER BY 3 NULLS LAST, a.fiscal_year, a.id
"""

_CSR_YEARS = f"""
SELECT fiscal_year, prescribed_csr, total_spent, spent_on_projects, unspent_transferred, local_area_spent,
       {source('x')}
FROM funder_csr_years x WHERE funder_id = %(id)s
ORDER BY fiscal_year DESC
"""

# Footprint rows are one per project place; the page needs states and their districts per year.
_FOOTPRINT = f"""
SELECT a.fiscal_year, COALESCE(s.name, {STATE_OF}) AS state,
       count(DISTINCT l.id) FILTER (WHERE l.kind = 'district') AS districts,
       COALESCE(array_agg(DISTINCT l.name ORDER BY l.name) FILTER (WHERE l.kind = 'district'), '{{}}')
         AS district_names,
       min({public_name('a.source_name', 'a.source_url')}) AS source_name, min({public_url('a.source_url')}) AS source_url
FROM funder_activity a
LEFT JOIN locations l ON l.id = a.location_id
LEFT JOIN locations lp ON lp.id = l.parent_id
LEFT JOIN locations s ON s.id = a.state_location_id
WHERE a.funder_id = %(id)s AND a.kind = 'footprint' AND a.is_public
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC, 2
"""

_STATED = f"""
SELECT l.name, l.kind, {STATE_OF} AS state, fl.role, {public_text('fl.note')} AS note, {source('fl')}
FROM funder_locations fl
JOIN locations l ON l.id = fl.location_id
LEFT JOIN locations lp ON lp.id = l.parent_id
WHERE fl.funder_id = %(id)s
ORDER BY fl.role, l.name
"""

_ELIGIBILITY = f"""
SELECT id, title, {public_text('content_md')} AS content_md, {source('d')}
FROM documents d WHERE funder_id = %(id)s AND doc_type = 'funder_eligibility' AND is_public
ORDER BY id
"""

_OPEN_CALLS = f"""
SELECT r.id, r.title, {public_url('r.url')} AS url, r.deadline, r.amount_min, r.amount_max,
       {public_url('r.source_url')} AS source_url
FROM rfps r WHERE r.funder_id = %(id)s AND {OPEN_CALL}
ORDER BY r.deadline NULLS LAST, r.id
"""

# Owner pool, no join to orgs or funders: the entity is already known to be visible to the caller.
_HIDDEN_CONTACTS = "SELECT count(DISTINCT name) AS n FROM contacts WHERE NOT is_public AND {owner} = %(id)s"

_RESEARCH = f"""
WITH runs AS (
  SELECT r.researched_on, r.sources_read FROM entity_research r
  WHERE {research_match("%(kind)s::text", "%(id)s::bigint", "%(slug)s::text")}
)
SELECT (SELECT count(*) FROM runs) AS runs, (SELECT max(researched_on) FROM runs) AS latest,
       COALESCE((SELECT json_agg(json_build_object('url', u, 'first_read', f) ORDER BY f, u)
                 FROM (SELECT u, min(researched_on) AS f FROM runs, unnest(sources_read) u
                       WHERE NOT {is_private_url('u')} GROUP BY u) s), '[]') AS sources
"""


async def _all(conn, sql: str, params: dict) -> list[dict]:
    return await (await conn.execute(sql, params)).fetchall()


def program_tree(programs: list[dict], tags: list[dict], metrics: list[dict]) -> list[dict]:
    """Each programme with its own tags and metrics; parent_id carries the tree."""
    by_id = {p["id"]: {**p, "tags": [], "metrics": []} for p in programs}
    for t in tags:
        if t["program_id"] in by_id:
            by_id[t["program_id"]]["tags"].append(t)
    for m in metrics:
        if m["program_id"] in by_id:
            by_id[m["program_id"]]["metrics"].append(m)
    return list(by_id.values())


async def _shared(conn, owner: str, tag_table: str, entity_id: int) -> dict[str, Any]:
    p = {"id": entity_id}
    programs = await _all(conn, _PROGRAMS.format(owner=owner), p)
    tags = await _all(conn, _PROGRAM_TAGS, {"pids": [x["id"] for x in programs]}) if programs else []
    metrics = await _all(conn, _METRICS.format(owner=owner), p)
    documents = await _all(conn, _DOCUMENTS.format(owner=owner), p)
    if documents:
        links = await _all(conn, _DOCUMENT_LINKS.format(owner=owner), {**p, "dids": [d["id"] for d in documents]})
        for d in documents:
            d["links"] = [lk for lk in links if lk["document_id"] == d["id"]]
    stories = await _all(conn, story_counts(owner), {"ids": [entity_id], "social": SOCIAL})
    return {
        "contacts": await _all(conn, _CONTACTS.format(owner=owner), p),
        "programs": program_tree(programs, tags, metrics),
        "metrics": metrics,
        "documents": documents,
        "tags": await _all(conn, entity_tags(owner, tag_table), {"ids": [entity_id]}),
        "sdgs": await _all(conn, entity_sdgs(owner, tag_table), {"ids": [entity_id]}),
        "stories": stories[0] if stories else {},
    }


async def _private(owner_pool: Any, kind: str, entity_id: int, slug: str) -> dict[str, Any]:
    """What only the owner can read, reduced to what any viewer may see."""
    col = "org_id" if kind == "org" else "funder_id"
    async with owner_pool.connection() as conn:
        hidden = await (await conn.execute(_HIDDEN_CONTACTS.format(owner=col), {"id": entity_id})).fetchone()
        research = await (await conn.execute(_RESEARCH, {"kind": kind, "id": entity_id, "slug": slug})).fetchone()
        identifiers = await _all(conn, IDENTIFIERS, {"ids": [entity_id]}) if kind == "org" else []
    return {"hidden_contacts": hidden["n"], "research": research, "identifiers": identifiers}


async def org_facts(pool: Any, owner_pool: Any, slug_or_id: str) -> OrgFacts | None:
    async with pool.connection() as conn:
        org = await (await conn.execute(_ORG, {"v": slug_or_id})).fetchone()
        if org is None:
            return None
        p = {"id": org["id"]}
        shared = await _shared(conn, "org_id", "org_tags", org["id"])
        places = await _all(conn, _PLACES, p)
        financials = await _all(conn, _FINANCIALS, p)
        funders = await group_page(conn, "org", org["id"], offset=0, limit=FIRST_PAGE)
    private = await _private(owner_pool, "org", org["id"], org["slug"])
    contacts = shared.pop("contacts")
    return OrgFacts.model_validate({
        **shared, "org": {**org, "contacts": contacts, "identifiers": private["identifiers"]},
        "places": places, "financials": financials, "funders": funders,
        "hidden_contacts": private["hidden_contacts"], "research": private["research"],
    })


async def funder_facts(pool: Any, owner_pool: Any, slug_or_id: str) -> FunderFacts | None:
    async with pool.connection() as conn:
        funder = await (await conn.execute(_FUNDER, {"v": slug_or_id})).fetchone()
        if funder is None:
            return None
        p = {"id": funder["id"]}
        shared = await _shared(conn, "funder_id", "funder_tags", funder["id"])
        rest = {
            "spend": await _all(conn, _SPEND, p),
            "csr_years": await _all(conn, _CSR_YEARS, p),
            "footprint": await _all(conn, _FOOTPRINT, p),
            "stated": await _all(conn, _STATED, p),
            "eligibility": await _all(conn, _ELIGIBILITY, p),
            "open_calls": await _all(conn, _OPEN_CALLS, p),
            "partners": await group_page(conn, "funder", funder["id"], offset=0, limit=FIRST_PAGE),
        }
    private = await _private(owner_pool, "funder", funder["id"], funder["slug"])
    contacts = shared.pop("contacts")
    return FunderFacts.model_validate({
        **shared, **rest, "funder": {**funder, "contacts": contacts},
        "hidden_contacts": private["hidden_contacts"], "research": private["research"],
    })

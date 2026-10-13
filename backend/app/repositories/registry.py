"""The Registry list: every visible org and funder with what its row, filters and search read.

Runs as the caller, so RLS decides which entities are listed; public rows only (is_public, visibility)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.repositories.news_stories import SOCIAL
from app.repositories.partner_groups import GROUP_KEY
from app.repositories.public_sql import (
    ON_FILE,
    OPEN_CALL,
    STATE_OF,
    entity_sdgs,
    entity_tags,
    research_match,
    story_counts,
)

_ORGS = """
SELECT o.id, o.slug, o.name, o.aliases, dl.name AS district, sl.name AS state
FROM orgs o
LEFT JOIN locations dl ON dl.id = o.registered_location_id
LEFT JOIN locations sl ON sl.id = dl.parent_id
ORDER BY o.name
"""

_FUNDERS = "SELECT id, slug, name, aliases, funder_type, intake_mode FROM funders ORDER BY name"

# Each place as (district or NULL, state); a state row has no district.
_ORG_PLACES = f"""
SELECT ol.org_id AS id, ol.role, CASE WHEN l.kind = 'district' THEN l.name END AS district, {STATE_OF} AS state
FROM org_locations ol
JOIN locations l ON l.id = ol.location_id
LEFT JOIN locations lp ON lp.id = l.parent_id
WHERE ol.org_id = ANY(%(ids)s)
"""

_FUNDER_PLACES = f"""
SELECT fl.funder_id AS id, fl.role, CASE WHEN l.kind = 'district' THEN l.name END AS district, {STATE_OF} AS state
FROM funder_locations fl
JOIN locations l ON l.id = fl.location_id
LEFT JOIN locations lp ON lp.id = l.parent_id
WHERE fl.funder_id = ANY(%(ids)s)
UNION
SELECT a.funder_id, 'footprint', CASE WHEN l.kind = 'district' THEN l.name END, COALESCE(s.name, {STATE_OF})
FROM funder_activity a
LEFT JOIN locations l ON l.id = a.location_id
LEFT JOIN locations lp ON lp.id = l.parent_id
LEFT JOIN locations s ON s.id = a.state_location_id
WHERE a.funder_id = ANY(%(ids)s) AND a.kind = 'footprint' AND a.is_public
"""

# On the owner pool, so a list filter reads the same for every viewer.
_ON_FILE = f"""
SELECT org_id AS id, array_agg(DISTINCT id_type) AS types
FROM org_identifiers WHERE org_id = ANY(%(ids)s) AND {ON_FILE}
GROUP BY org_id
"""

_PROGRAMS = """
SELECT {owner} AS id, string_agg(name, ' ') AS names FROM programs WHERE {owner} = ANY(%(ids)s) GROUP BY 1
"""

_ORG_FUNDERS = """
SELECT a.partner_org_id AS id, count(DISTINCT a.funder_id) AS n, string_agg(DISTINCT f.name, ' ') AS names
FROM funder_activity a JOIN funders f ON f.id = a.funder_id
WHERE a.kind = 'partner' AND a.is_public AND a.partner_org_id = ANY(%(ids)s)
GROUP BY 1
"""

# Partners counted as the profile groups them.
_FUNDER_PARTNERS = f"""
SELECT a.funder_id AS id, count(DISTINCT {GROUP_KEY["funder"]}) AS n, string_agg(DISTINCT a.partner_name, ' ') AS names
FROM funder_activity a
WHERE a.kind = 'partner' AND a.is_public AND a.funder_id = ANY(%(ids)s)
GROUP BY 1
"""

_OPEN_CALLS = f"SELECT DISTINCT r.funder_id AS id FROM rfps r WHERE r.funder_id = ANY(%(ids)s) AND {OPEN_CALL}"

_CSR = """
SELECT DISTINCT ON (funder_id) funder_id AS id, fiscal_year, prescribed_csr
FROM funder_csr_years
WHERE funder_id = ANY(%(ids)s) AND prescribed_csr IS NOT NULL
ORDER BY funder_id, fiscal_year DESC
"""


async def _by_id(conn, sql: str, ids: list[int], **extra) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for row in await (await conn.execute(sql, {"ids": ids, **extra})).fetchall():
        out[row["id"]].append(row)
    return out


def _places(rows: list[dict]) -> tuple[str | None, list[str], list[str]]:
    """(leading "District, State", every state, every district) — the state with the most districts leads."""
    worked = [r for r in rows if r["role"] != "registered"] or rows
    per_state: dict[str, list[str]] = defaultdict(list)
    for r in worked:
        if r["state"]:
            per_state[r["state"]] += [r["district"]] if r["district"] else []
    states = sorted(per_state, key=lambda s: (-len(set(per_state[s])), s))
    lead = states[0] if states else None
    district = min(per_state[lead]) if lead and per_state[lead] else None
    place = ", ".join(x.title() if x and x.isupper() else x for x in (district, lead) if x) or None
    districts = sorted({r["district"] for r in rows if r["district"]})
    return place, states, districts


def _themes(tags: list[dict]) -> tuple[list[dict], list[str]]:
    themes = [{"label": t["label"], "domain": t["domain"]} for t in tags if t["kind"] in ("theme", "sub_theme")]
    lenses = [t["label"] for t in tags if t["kind"] in ("population", "lens")]
    return themes, lenses


_NO_STORIES = {"press": 0, "social": 0, "posts_since": None}


def _search(*parts) -> str:
    return " ".join(str(p) for p in parts if p).lower()


async def registry_rows(pool: Any, owner: Any) -> list[dict]:
    """Entities as the caller may see them (RLS); registrations on the owner, the same for everyone."""
    rows: list[dict] = []
    async with pool.connection() as conn:
        orgs = await (await conn.execute(_ORGS)).fetchall()
        funders = await (await conn.execute(_FUNDERS)).fetchall()
        oids, fids = [o["id"] for o in orgs], [f["id"] for f in funders]

        o_places = await _by_id(conn, _ORG_PLACES, oids)
        o_tags = await _by_id(conn, entity_tags("org_id", "org_tags"), oids)
        o_sdgs = await _by_id(conn, entity_sdgs("org_id", "org_tags"), oids)
        o_progs = await _by_id(conn, _PROGRAMS.format(owner="org_id"), oids)
        o_funders = await _by_id(conn, _ORG_FUNDERS, oids)
        o_news = await _by_id(conn, story_counts("org_id"), oids, social=SOCIAL)

        f_places = await _by_id(conn, _FUNDER_PLACES, fids)
        f_tags = await _by_id(conn, entity_tags("funder_id", "funder_tags"), fids)
        f_sdgs = await _by_id(conn, entity_sdgs("funder_id", "funder_tags"), fids)
        f_progs = await _by_id(conn, _PROGRAMS.format(owner="funder_id"), fids)
        f_partners = await _by_id(conn, _FUNDER_PARTNERS, fids)
        f_open = await _by_id(conn, _OPEN_CALLS, fids)
        f_csr = await _by_id(conn, _CSR, fids)
        f_news = await _by_id(conn, story_counts("funder_id"), fids, social=SOCIAL)
    async with owner.connection() as conn:
        o_ids = await _by_id(conn, _ON_FILE, oids)

    for o in orgs:
        i = o["id"]
        place, states, districts = _places(o_places[i])
        if not place and o["district"]:
            place = ", ".join(x for x in (o["district"].title(), o["state"]) if x)
        themes, lenses = _themes(o_tags[i])
        types = set(o_ids[i][0]["types"]) if o_ids[i] else set()
        funded = o_funders[i][0] if o_funders[i] else {"n": 0, "names": ""}
        news = o_news[i][0] if o_news[i] else _NO_STORIES
        rows.append({
            "kind": "org", "id": i, "slug": o["slug"], "name": o["name"], "place": place, "states": states,
            "themes": themes, "lenses": lenses, "sdgs": [s["code"] for s in o_sdgs[i]],
            "csr1": "csr1" in types, "has_12a_80g": {"12a", "80g"} <= types, "fcra": "fcra" in types,
            "partners": funded["n"], "press": news["press"], "social": news["social"], "posts_since": news["posts_since"],
            "search": _search(o["name"], *(o["aliases"] or []), *districts, *states,
                              o_progs[i][0]["names"] if o_progs[i] else "", funded["names"]),
        })
    for f in funders:
        i = f["id"]
        _, states, districts = _places(f_places[i])
        themes, lenses = _themes(f_tags[i])
        partners = f_partners[i][0] if f_partners[i] else {"n": 0, "names": ""}
        csr = f_csr[i][0] if f_csr[i] else {"fiscal_year": None, "prescribed_csr": None}
        news = f_news[i][0] if f_news[i] else _NO_STORIES
        rows.append({
            "kind": "funder", "id": i, "slug": f["slug"], "name": f["name"], "funder_type": f["funder_type"],
            "states": states, "themes": themes, "lenses": lenses, "sdgs": [s["code"] for s in f_sdgs[i]],
            "intake_mode": f["intake_mode"], "open_call": bool(f_open[i]), "partners": partners["n"],
            "csr_prescribed": csr["prescribed_csr"], "csr_year": csr["fiscal_year"],
            "press": news["press"], "social": news["social"], "posts_since": news["posts_since"],
            "search": _search(f["name"], *(f["aliases"] or []), *districts, *states,
                              f_progs[i][0]["names"] if f_progs[i] else "", partners["names"]),
        })
    return rows


# On the owner pool: entity_research is staff-only, and the list shows only a count and a date.
_RESEARCH = f"""
WITH e AS (SELECT * FROM unnest(%(kinds)s::text[], %(ids)s::bigint[], %(slugs)s::text[]) AS e(kind, id, slug))
SELECT e.kind, e.id, count(*) AS runs, max(r.researched_on) AS latest
FROM e JOIN entity_research r ON {research_match("e.kind", "e.id", "e.slug")}
GROUP BY 1, 2
"""


async def research_counts(pool: Any, entities: list[tuple[str, int, str]]) -> dict[tuple[str, int], dict]:
    params = {"kinds": [k for k, _, _ in entities], "ids": [i for _, i, _ in entities],
              "slugs": [s for _, _, s in entities]}
    async with pool.connection() as conn:
        rows = await (await conn.execute(_RESEARCH, params)).fetchall()
    return {(r["kind"], r["id"]): {"runs": r["runs"], "latest": r["latest"]} for r in rows}

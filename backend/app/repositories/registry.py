"""The Registry list: every visible org and funder with what its row, filters and search read.

Runs as the caller, so RLS decides which entities are listed; public rows only (is_public, visibility)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from app.repositories.facets import ordered
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

# On the owner pool, so a badge and a filter read the same for every viewer; only for the orgs asked about.
_ON_FILE = f"""
SELECT org_id AS id, array_agg(DISTINCT id_type) AS types
FROM org_identifiers WHERE org_id = ANY(%(ids)s) AND {ON_FILE}
GROUP BY org_id
"""

# The orgs with every registration in %(needs)s on file: what the Registrations filter keeps.
_REGISTERED = f"""
SELECT org_id AS id FROM org_identifiers WHERE id_type = ANY(%(needs)s) AND {ON_FILE}
GROUP BY org_id HAVING count(DISTINCT id_type) = cardinality(%(needs)s::text[])
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


async def _pipelined(conn, queries: list[tuple[str, dict]]) -> list[list[dict]]:
    """Every query in one round trip rather than one each."""
    async with conn.pipeline():
        cursors = [await conn.execute(sql, params) for sql, params in queries]
        return [await c.fetchall() for c in cursors]


def _by_id(rows: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        out[row["id"]].append(row)
    return out


_ORG_DETAILS = (_ORG_PLACES, entity_tags("org_id", "org_tags"), entity_sdgs("org_id", "org_tags"),
                _PROGRAMS.format(owner="org_id"), _ORG_FUNDERS, story_counts("org_id"))
_FUNDER_DETAILS = (_FUNDER_PLACES, entity_tags("funder_id", "funder_tags"), entity_sdgs("funder_id", "funder_tags"),
                   _PROGRAMS.format(owner="funder_id"), _FUNDER_PARTNERS, _OPEN_CALLS, _CSR,
                   story_counts("funder_id"))


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
    # Most programmes first, so a row leads with the work the entity does most; ties keep role, then label.
    tags = sorted(tags, key=lambda t: -t["progs"])
    themes = [{"label": t["label"], "domain": t["domain"]} for t in tags if t["kind"] in ("theme", "sub_theme")]
    populations = [t["label"] for t in tags if t["kind"] == "population"]
    return themes, populations


_NO_STORIES = {"press": 0, "social": 0, "posts_since": None}


def _search(*parts) -> str:
    return " ".join(str(p) for p in parts if p).lower()


async def _add_registrations(owner: Any, rows: list[dict]) -> list[dict]:
    """Each org row's registration flags, read for those orgs only; after the caller's connection is returned,
    since both come from one pool and holding two at once could wait on itself."""
    ids = [r["id"] for r in rows if r["kind"] == "org"]
    if ids:
        async with owner.connection() as conn:
            found = await (await conn.execute(_ON_FILE, {"ids": ids})).fetchall()
        on_file = {r["id"]: set(r["types"]) for r in found}
        for r in rows:
            if r["kind"] == "org":
                types = on_file.get(r["id"], set())
                r.update(csr1="csr1" in types, has_12a_80g={"12a", "80g"} <= types, fcra="fcra" in types)
    return rows


async def _registered(owner: Any, needs: list[str]) -> list[int]:
    async with owner.connection() as conn:
        return [r["id"] for r in await (await conn.execute(_REGISTERED, {"needs": needs})).fetchall()]


async def _rows(conn, orgs: list[dict], funders: list[dict]) -> list[dict]:
    """The Registry rows of these orgs and funders, in the order given; registrations come from _add_registrations."""
    rows: list[dict] = []
    # A kind with no entities on this page sends none of its queries.
    oids = {"ids": [o["id"] for o in orgs], "social": SOCIAL}
    fids = {"ids": [f["id"] for f in funders], "social": SOCIAL}
    org_qs, funder_qs = _ORG_DETAILS if orgs else (), _FUNDER_DETAILS if funders else ()
    found = iter(await _pipelined(conn, [(q, oids) for q in org_qs] + [(q, fids) for q in funder_qs]))
    o_places, o_tags, o_sdgs, o_progs, o_funders, o_news = (
        _by_id(next(found) if orgs else []) for _ in _ORG_DETAILS)
    f_places, f_tags, f_sdgs, f_progs, f_partners, f_open, f_csr, f_news = (
        _by_id(next(found) if funders else []) for _ in _FUNDER_DETAILS)

    for o in orgs:
        i = o["id"]
        place, states, districts = _places(o_places[i])
        if not place and o["district"]:
            place = ", ".join(x for x in (o["district"].title(), o["state"]) if x)
        themes, populations = _themes(o_tags[i])
        funded = o_funders[i][0] if o_funders[i] else {"n": 0, "names": ""}
        news = o_news[i][0] if o_news[i] else _NO_STORIES
        rows.append({
            "kind": "org", "id": i, "slug": o["slug"], "name": o["name"], "place": place, "states": states,
            "themes": themes, "populations": populations, "sdgs": [s["code"] for s in o_sdgs[i]],
            "csr1": False, "has_12a_80g": False, "fcra": False, "partners": funded["n"], "press": news["press"], "social": news["social"], "posts_since": news["posts_since"],
            "search": _search(o["name"], *(o["aliases"] or []), *districts, *states,
                              o_progs[i][0]["names"] if o_progs[i] else "", funded["names"]),
        })
    for f in funders:
        i = f["id"]
        _, states, districts = _places(f_places[i])
        themes, populations = _themes(f_tags[i])
        partners = f_partners[i][0] if f_partners[i] else {"n": 0, "names": ""}
        csr = f_csr[i][0] if f_csr[i] else {"fiscal_year": None, "prescribed_csr": None}
        news = f_news[i][0] if f_news[i] else _NO_STORIES
        rows.append({
            "kind": "funder", "id": i, "slug": f["slug"], "name": f["name"], "funder_type": f["funder_type"],
            "states": states, "themes": themes, "populations": populations, "sdgs": [s["code"] for s in f_sdgs[i]],
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


# Kept in step with frontend/features/registry/rows.ts, which a test checks.
NORTH_EAST = ("Arunachal Pradesh", "Assam", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Sikkim", "Tripura")


@dataclass(frozen=True)
class Filters:
    """The Registry's filters, with the defaults of frontend/features/registry/filtersUrl.ts."""

    kind: str = "all"  # 'all' | 'org' | 'funder'
    theme: str = "all"
    population: str = "all"
    sdg: str = "all"
    where: str = "any"  # 'any' | 'ne' | 'out' | a state
    reg: str = "any"
    ftype: str = "all"
    approach: str = "any"
    q: str = ""


# The dropdowns, as _FACETS names them; SDGs go in number order.
_FACET_NAMES = ("theme", "population", "sdg", "where", "ftype", "approach")
_NUMERIC = {"sdg"}


def _over_all(sql: str, table: str) -> str:
    """A per-entity query above, over every row of `table` the caller sees rather than %(ids)s."""
    return sql.replace("%(ids)s", f"ARRAY(SELECT id FROM {table})")


# One lean row per entity with only what the filters, the sort and the search read: the same pieces as
# _rows, so a row cannot say something its filters do not read.
_INDEX = f"""
places AS MATERIALIZED (
  SELECT 'org' AS kind, p.id, p.role, p.district, p.state FROM ({_over_all(_ORG_PLACES, "orgs")}) p
  UNION ALL
  SELECT 'funder', p.id, p.role, p.district, p.state FROM ({_over_all(_FUNDER_PLACES, "funders")}) p
),
worked AS (
  SELECT kind, id, state, count(DISTINCT district) AS n
  FROM (SELECT *, bool_or(role IS DISTINCT FROM 'registered') OVER (PARTITION BY kind, id) AS any_worked
        FROM places) p
  WHERE state <> '' AND (role IS DISTINCT FROM 'registered' OR NOT any_worked)
  GROUP BY 1, 2, 3
),
st AS (SELECT kind, id, array_agg(state ORDER BY n DESC, state COLLATE "C") AS states FROM worked GROUP BY 1, 2),
ds AS (
  SELECT kind, id, array_agg(DISTINCT (district COLLATE "C") ORDER BY (district COLLATE "C")) AS districts
  FROM places WHERE district <> '' GROUP BY 1, 2
),
tg AS (
  SELECT kind, id, array_agg(domain) FILTER (WHERE tkind IN ('theme', 'sub_theme')) AS domains,
         array_agg(label) FILTER (WHERE tkind = 'population') AS populations
  FROM (SELECT 'org' AS kind, t.id, t.kind AS tkind, t.label, t.domain
        FROM ({_over_all(entity_tags("org_id", "org_tags"), "orgs")}) t
        UNION ALL
        SELECT 'funder', t.id, t.kind, t.label, t.domain
        FROM ({_over_all(entity_tags("funder_id", "funder_tags"), "funders")}) t) x
  GROUP BY 1, 2
),
sd AS (
  SELECT kind, id, array_agg(code) AS sdgs
  FROM (SELECT 'org' AS kind, s.id, s.code FROM ({_over_all(entity_sdgs("org_id", "org_tags"), "orgs")}) s
        UNION ALL
        SELECT 'funder', s.id, s.code FROM ({_over_all(entity_sdgs("funder_id", "funder_tags"), "funders")}) s) x
  GROUP BY 1, 2
),
names AS (
  SELECT 'org' AS kind, p.id, p.names AS progs, NULL AS partners
  FROM ({_over_all(_PROGRAMS.format(owner="org_id"), "orgs")}) p
  UNION ALL SELECT 'funder', p.id, p.names, NULL FROM ({_over_all(_PROGRAMS.format(owner="funder_id"), "funders")}) p
  UNION ALL SELECT 'org', p.id, NULL, p.names FROM ({_over_all(_ORG_FUNDERS, "orgs")}) p
  UNION ALL SELECT 'funder', p.id, NULL, p.names FROM ({_over_all(_FUNDER_PARTNERS, "funders")}) p
),
nm AS (SELECT kind, id, max(progs) AS progs, max(partners) AS partners FROM names GROUP BY 1, 2),
ent AS (
  SELECT 'org' AS kind, o.id, o.slug, o.name, o.aliases, dl.name AS district, sl.name AS state,
         NULL::text AS funder_type, NULL::text AS intake_mode, false AS open_call
  FROM orgs o
  LEFT JOIN locations dl ON dl.id = o.registered_location_id
  LEFT JOIN locations sl ON sl.id = dl.parent_id
  UNION ALL
  SELECT 'funder', f.id, f.slug, f.name, f.aliases, NULL, NULL, f.funder_type::text, f.intake_mode::text,
         f.id IN (SELECT oc.id FROM ({_over_all(_OPEN_CALLS, "funders")}) oc)
  FROM funders f
),
idx AS MATERIALIZED (
  SELECT e.*, coalesce(st.states, '{{}}') AS states, coalesce(tg.domains, '{{}}') AS domains,
         coalesce(tg.populations, '{{}}') AS populations, coalesce(sd.sdgs, '{{}}') AS sdgs,
         lower(array_to_string(array_remove(
           ARRAY[e.name] || coalesce(e.aliases, '{{}}') || coalesce(ds.districts, '{{}}')
           || coalesce(st.states, '{{}}') || ARRAY[nm.progs, nm.partners], ''), ' ')) AS search
  FROM ent e
  LEFT JOIN st USING (kind, id) LEFT JOIN ds USING (kind, id) LEFT JOIN tg USING (kind, id)
  LEFT JOIN sd USING (kind, id) LEFT JOIN nm USING (kind, id)
)"""

_FACETS = """
SELECT 'kind' AS facet, kind AS value, count(*) AS n FROM idx GROUP BY 2
UNION ALL SELECT 'theme', v, count(DISTINCT (kind, id)) FROM idx, unnest(domains) v WHERE v <> '' GROUP BY 2
UNION ALL SELECT 'population', v, count(DISTINCT (kind, id)) FROM idx, unnest(populations) v WHERE v <> '' GROUP BY 2
UNION ALL SELECT 'sdg', v, count(DISTINCT (kind, id)) FROM idx, unnest(sdgs) v WHERE v <> '' GROUP BY 2
UNION ALL SELECT 'where', v, count(DISTINCT (kind, id)) FROM idx, unnest(states) v WHERE v <> '' GROUP BY 2
UNION ALL SELECT 'ftype', funder_type, count(*) FROM idx WHERE kind = 'funder' AND funder_type <> '' GROUP BY 2
UNION ALL SELECT 'approach', 'open', count(*) FROM idx WHERE open_call HAVING count(*) > 0
UNION ALL SELECT 'approach', 'invites', count(*) FROM idx WHERE intake_mode = 'invitation_only' HAVING count(*) > 0
"""

# The registrations each Registrations option needs on file.
_REG_NEEDS = {"csr1": ["csr1"], "12a80g": ["12a", "80g"], "fcra": ["fcra"]}


def _where(f: Filters, reg_ids: list[int] | None) -> tuple[str, dict]:
    """The filters and the search, as a WHERE clause over idx."""
    conds = ["true"]
    q = f.q.strip().lower()
    params = {"kind": f.kind, "theme": f.theme, "population": f.population, "sdg": f.sdg, "where": f.where,
              "ftype": f.ftype, "q": q, "ne": list(NORTH_EAST)}
    if f.kind != "all":
        conds.append("kind = %(kind)s")
    if f.theme != "all":
        conds.append("%(theme)s = ANY(domains)")
    if f.population != "all":
        conds.append("%(population)s = ANY(populations)")
    if f.sdg != "all":
        conds.append("%(sdg)s = ANY(sdgs)")
    if f.where == "ne":
        conds.append("states && %(ne)s::text[]")
    elif f.where == "out":
        conds.append("EXISTS (SELECT 1 FROM unnest(states) s WHERE s <> ALL(%(ne)s::text[]))")
    elif f.where != "any":
        conds.append("%(where)s = ANY(states)")
    if reg_ids is not None:
        conds.append("id = ANY(%(reg_ids)s::bigint[])")
        params["reg_ids"] = reg_ids
    if f.kind == "funder":
        if f.ftype != "all":
            conds.append("funder_type = %(ftype)s")
        if f.approach == "open":
            conds.append("open_call")
        elif f.approach == "invites":
            conds.append("intake_mode = 'invitation_only'")
    if q:
        conds.append("strpos(search, %(q)s) > 0")
    return " AND ".join(conds), params


async def registry_page_sql(pool: Any, owner: Any, f: Filters, *, limit: int, offset: int) -> dict:
    """One page of what `f` keeps (CSOs first, then funders, each A→Z), its total, and on the first page only the
    cards' counts and the dropdowns, which change with the filters and not with scrolling."""
    reg_ids = await _registered(owner, _REG_NEEDS[f.reg]) if f.kind == "org" and f.reg in _REG_NEEDS else None
    where, params = _where(f, reg_ids)
    sql = f"""
WITH {_INDEX.lstrip()},
kept AS (SELECT * FROM idx WHERE {where}),
page AS (
  SELECT kind, id, slug, name, aliases, district, state, funder_type, intake_mode,
         kind <> 'org' AS k1, lower(name) COLLATE "C" AS k2
  FROM kept ORDER BY k1, k2, id LIMIT %(limit)s OFFSET %(offset)s
),
facets AS (SELECT * FROM ({_FACETS}) f WHERE %(with_facets)s)
SELECT (SELECT count(*) FROM kept) AS total,
       (SELECT coalesce(json_agg(page ORDER BY k1, k2, id), '[]') FROM page) AS page,
       (SELECT coalesce(json_agg(facets), '[]') FROM facets) AS facets"""
    query = {**params, "limit": limit, "offset": offset, "with_facets": offset == 0}
    async with pool.connection() as conn:
        res = await (await conn.execute(sql, query)).fetchone()
        page = res["page"]
        items = await _rows(conn, [e for e in page if e["kind"] == "org"], [e for e in page if e["kind"] == "funder"])
    items = await _add_registrations(owner, items)
    return {"items": items, "total": res["total"], "limit": limit, "offset": offset, **_facets(res["facets"])}


def _facets(rows: list[dict]) -> dict:
    """The cards' counts and the dropdowns from _FACETS' rows; a later page has none."""
    if not rows:
        return {"counts": {}, "facets": {}}
    counts: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        counts[r["facet"]][r["value"]] = r["n"]
    return {"counts": {"all": sum(counts["kind"].values()), **counts["kind"]},
            "facets": {name: ordered(counts[name], name in _NUMERIC) for name in _FACET_NAMES}}

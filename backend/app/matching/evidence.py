"""What the engine knows about one org and each funder, loaded once per kind."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.matching.models import Basis, FunderRef, OrgRef


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    basis: Basis
    cite: str
    as_of: str | None = None
    document_id: int | None = None
    valid_until: date | None = None


@dataclass(frozen=True)
class Doc:
    id: int
    doc_type: str
    vault: bool
    """Uploaded through the Vault (uploaded_by set), as opposed to archived by research."""
    title: str | None = None


@dataclass(frozen=True)
class Project:
    source: str
    id: int
    cite: str
    funder: bool = False
    amount: bool = False
    theme: bool = False
    duration: bool = False
    results: bool = False

    def missing(self, fields: tuple[str, ...]) -> list[str]:
        return [f for f in fields if not getattr(self, f)]


@dataclass(frozen=True)
class OrgEvidence:
    org: OrgRef
    districts: dict[int, str] = field(default_factory=dict)
    states: dict[int, str] = field(default_factory=dict)
    """Includes the parent state of every district (R1)."""
    clauses: dict[str, str] = field(default_factory=dict)
    """Schedule VII slug -> label, through tags.meta->>'maps_to'."""
    identifiers: dict[str, Fact] = field(default_factory=dict)
    credential_events: dict[str, Fact] = field(default_factory=dict)
    """The latest event per credential."""
    financials: tuple[Fact, ...] = ()
    board: tuple[Fact, ...] = ()
    documents: dict[str, tuple[Doc, ...]] = field(default_factory=dict)
    projects: tuple[Project, ...] = ()
    not_found: tuple[tuple[str, date], ...] = ()
    """Concepts research looked for and did not find, with the day it looked."""

    @property
    def cite(self) -> str:
        return f"[org:{self.org.id}]"


@dataclass(frozen=True)
class PairFit:
    """Stage 1's row for one funder, relative to one org: what the two share."""

    shared_districts: tuple[str, ...] = ()
    shared_states: tuple[str, ...] = ()
    pan_india: bool = False
    regions: tuple[str, ...] = ()
    stated_places: int = 0
    """funder_locations rows with role 'funds': the only rows that can rule a place out (R4)."""
    observed_places: int = 0
    tag_clauses: tuple[str, ...] = ()
    asserted_tag_clauses: tuple[str, ...] = ()
    """From tags a person set (is_inferred false): the only ones that can rule a theme out."""
    shared_tag_clauses: tuple[str, ...] = ()
    tagged_programmes: int = 0
    asserted_programmes: int = 0
    shared_programmes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FunderEvidence:
    funder: FunderRef
    fit: PairFit = PairFit()

    @property
    def cite(self) -> str:
        return f"[funder:{self.funder.id}]"


# --- loaders ----------------------------------------------------------------------------------

ORG_KINDS = frozenset({"org.places", "org.themes", "org.identifiers", "org.credential_events",
                       "org.financials", "org.board", "org.documents", "org.projects", "org.research"})
FUNDER_KINDS: frozenset[str] = frozenset()
"""Funder-side stage-2 kinds. Empty until M5 adds funder.requirements."""
PAIR_KINDS = frozenset({"pair.fit"})

# A tag's Schedule VII clause: itself if it is one, else its sector's maps_to. Needs `t` and `cs`.
_CLAUSE_JOIN = ("JOIN tags cs ON cs.kind = 'csr_sector' "
                "AND cs.slug = CASE WHEN t.kind = 'csr_sector' THEN t.slug ELSE t.meta->>'maps_to' END")


def _refuse_unknown(reads, prefix: str, known: frozenset[str]) -> None:
    unknown = {r for r in reads if r.startswith(prefix)} - known
    if unknown:
        raise ValueError(f"no loader for evidence kinds: {sorted(unknown)}")


async def _rows(conn: Any, sql: str, params: Any = ()) -> list[dict]:
    return await (await conn.execute(sql, params)).fetchall()


async def _places(conn, org_id: int) -> dict:
    rows = await _rows(conn, """
        SELECT DISTINCT l.id, l.kind, l.name, p.id AS parent_id, p.kind AS parent_kind, p.name AS parent_name
        FROM locations l LEFT JOIN locations p ON p.id = l.parent_id
        WHERE l.id IN (SELECT location_id FROM org_locations
                       WHERE org_id = %(o)s AND (valid_to IS NULL OR valid_to >= current_date)
                       UNION SELECT registered_location_id FROM orgs WHERE id = %(o)s)""", {"o": org_id})
    districts = {r["id"]: r["name"] for r in rows if r["kind"] == "district"}
    states = {r["id"]: r["name"] for r in rows if r["kind"] == "state"}
    states |= {r["parent_id"]: r["parent_name"] for r in rows
               if r["kind"] == "district" and r["parent_kind"] == "state"}
    return {"districts": districts, "states": states}


async def _themes(conn, org_id: int) -> dict:
    rows = await _rows(conn, f"SELECT DISTINCT cs.slug, cs.label FROM org_tags ot JOIN tags t ON t.id = ot.tag_id "
                             f"{_CLAUSE_JOIN} WHERE ot.org_id = %s ORDER BY cs.slug", (org_id,))
    return {"clauses": {r["slug"]: r["label"] for r in rows}}


async def _identifiers(conn, org_id: int, cite: str) -> dict:
    rows = await _rows(conn, "SELECT DISTINCT ON (id_type) id_type, id_value, as_of, document_id "
                             "FROM org_identifiers WHERE org_id = %s AND is_current "
                             "ORDER BY id_type, verified DESC", (org_id,))
    return {"identifiers": {r["id_type"]: Fact(r["id_type"], r["id_value"], "recorded", cite, r["as_of"],
                                               r["document_id"]) for r in rows}}


async def _credential_events(conn, org_id: int, cite: str) -> dict:
    # check_blocked says nothing either way, so it must not hide an earlier decisive event (R10).
    rows = await _rows(conn, "SELECT DISTINCT ON (credential) credential, event, event_date, valid_until, "
                             "document_id FROM credential_events WHERE org_id = %s AND event <> 'check_blocked' "
                             "ORDER BY credential, event_date DESC, id DESC", (org_id,))
    return {"credential_events": {
        r["credential"]: Fact(r["credential"], r["event"], "recorded", cite, r["event_date"].isoformat(),
                              r["document_id"], r["valid_until"]) for r in rows}}


async def _financials(conn, org_id: int, cite: str) -> dict:
    rows = await _rows(conn, "SELECT fiscal_year, total_income, program_spend, non_program_spend, "
                             "foreign_contribution, is_audited, as_of, document_id FROM org_financials "
                             "WHERE org_id = %s ORDER BY fiscal_year", (org_id,))
    money = ("total_income", "program_spend", "non_program_spend", "foreign_contribution", "is_audited")
    return {"financials": tuple(Fact(r["fiscal_year"], {k: r[k] for k in money}, "recorded", cite, r["as_of"],
                                     r["document_id"]) for r in rows)}


async def _board(conn, org_id: int, cite: str) -> dict:
    rows = await _rows(conn, "SELECT name, role, as_of, document_id FROM contacts "
                             "WHERE org_id = %s AND kind = 'office_bearer' ORDER BY name, id", (org_id,))
    return {"board": tuple(Fact(r["name"], r["role"], "recorded", cite, r["as_of"], r["document_id"])
                           for r in rows)}


async def _documents(conn, org_id: int) -> dict:
    rows = await _rows(conn, "SELECT id, doc_type, uploaded_by IS NOT NULL AS vault, title FROM documents "
                             "WHERE org_id = %s AND doc_type IS NOT NULL AND status <> 'requested' "
                             "ORDER BY doc_type, id", (org_id,))
    docs: dict[str, list[Doc]] = {}
    for r in rows:
        docs.setdefault(r["doc_type"], []).append(Doc(r["id"], r["doc_type"], r["vault"], r["title"]))
    return {"documents": {k: tuple(v) for k, v in docs.items()}}


async def _projects(conn, org_id: int, cite: str) -> dict:
    rows = await _rows(conn, """
        SELECT 'grant' AS source, g.id, true AS funder, g.amount IS NOT NULL AS amount,
               EXISTS (SELECT 1 FROM program_tags pt WHERE pt.program_id = g.program_id) AS theme,
               g.start_date IS NOT NULL AND g.end_date IS NOT NULL AS duration, g.outcomes <> '{}' AS results
        FROM grants g WHERE g.org_id = %(o)s AND g.valid_to IS NULL
        UNION ALL
        SELECT 'programme', p.id, p.details ? 'funder', p.details ? 'amount',
               EXISTS (SELECT 1 FROM program_tags pt WHERE pt.program_id = p.id),
               p.start_date IS NOT NULL AND p.end_date IS NOT NULL, p.details ?| array['results', 'outcomes']
        FROM programs p WHERE p.org_id = %(o)s AND p.kind IN ('programme', 'project')
        ORDER BY 1, 2""", {"o": org_id})
    return {"projects": tuple(
        Project(r["source"], r["id"], f"[grant:{r['id']}]" if r["source"] == "grant" else cite,
                r["funder"], r["amount"], r["theme"], r["duration"], r["results"]) for r in rows)}


async def _research(conn, org_id: int) -> dict:
    rows = await _rows(conn, "SELECT concept, max(researched_on) AS researched_on FROM entity_research, "
                             "unnest(not_found) AS concept WHERE resolved_org_id = %s "
                             "GROUP BY concept ORDER BY concept", (org_id,))
    return {"not_found": tuple((r["concept"], r["researched_on"]) for r in rows)}


async def load_org(conn: Any, org_id: int, reads) -> OrgEvidence:
    """One query for the org, then one per evidence kind in `reads`."""
    _refuse_unknown(reads, "org.", ORG_KINDS)
    rows = await _rows(conn, "SELECT id, name, slug FROM orgs WHERE id = %s", (org_id,))
    if not rows:
        raise LookupError(f"org {org_id} not found")
    ref = OrgRef(id=rows[0]["id"], name=rows[0]["name"], slug=rows[0]["slug"])
    cite = f"[org:{org_id}]"
    loaders = {
        "org.places": lambda: _places(conn, org_id),
        "org.themes": lambda: _themes(conn, org_id),
        "org.identifiers": lambda: _identifiers(conn, org_id, cite),
        "org.credential_events": lambda: _credential_events(conn, org_id, cite),
        "org.financials": lambda: _financials(conn, org_id, cite),
        "org.board": lambda: _board(conn, org_id, cite),
        "org.documents": lambda: _documents(conn, org_id),
        "org.projects": lambda: _projects(conn, org_id, cite),
        "org.research": lambda: _research(conn, org_id),
    }
    fields: dict = {}
    for kind in sorted(ORG_KINDS & set(reads)):
        fields |= await loaders[kind]()
    return OrgEvidence(org=ref, **fields)


# Stage 1: every funder against one org's places and clauses, in one query (R2, R3, R4).
FIT_SQL = f"""
WITH place AS (
    SELECT fl.funder_id, l.id, l.kind, l.name, p.id AS parent_id, p.name AS parent_name,
           fl.role = 'funds' AS stated, true AS declared
    FROM funder_locations fl JOIN locations l ON l.id = fl.location_id LEFT JOIN locations p ON p.id = l.parent_id
    WHERE fl.role <> 'registered' AND (fl.valid_to IS NULL OR fl.valid_to >= current_date)
    UNION ALL
    SELECT ff.funder_id, l.id, l.kind, l.name, p.id, p.name, false, false
    FROM funder_footprints ff JOIN locations l ON l.id = ff.location_id LEFT JOIN locations p ON p.id = l.parent_id
), places AS (
    SELECT funder_id,
        array_agg(DISTINCT name ORDER BY name) FILTER (WHERE kind = 'district' AND id = ANY(%(d)s)) AS shared_districts,
        array_agg(DISTINCT CASE WHEN kind = 'state' THEN name ELSE parent_name END
                  ORDER BY CASE WHEN kind = 'state' THEN name ELSE parent_name END)
            FILTER (WHERE (kind = 'state' AND id = ANY(%(s)s))
                       OR (kind = 'district' AND parent_id = ANY(%(s)s))) AS shared_states,
        coalesce(bool_or(declared AND kind = 'country'), false) AS pan_india,
        array_agg(DISTINCT name ORDER BY name) FILTER (WHERE declared AND kind = 'region') AS regions,
        count(DISTINCT id) FILTER (WHERE stated) AS stated_places,
        count(DISTINCT id) FILTER (WHERE NOT stated) AS observed_places
    FROM place GROUP BY funder_id
), funder_clauses AS (
    SELECT ft.funder_id, array_agg(DISTINCT cs.slug ORDER BY cs.slug) AS tag_clauses,
        array_agg(DISTINCT cs.slug ORDER BY cs.slug) FILTER (WHERE NOT ft.is_inferred) AS asserted_tag_clauses,
        array_agg(DISTINCT cs.slug ORDER BY cs.slug) FILTER (WHERE cs.slug = ANY(%(c)s)) AS shared_tag_clauses
    FROM funder_tags ft JOIN tags t ON t.id = ft.tag_id {_CLAUSE_JOIN} GROUP BY ft.funder_id
), programmes AS (
    SELECT p.funder_id, count(DISTINCT p.id) AS tagged_programmes,
        count(DISTINCT p.id) FILTER (WHERE NOT pt.is_inferred) AS asserted_programmes,
        array_agg(DISTINCT p.name ORDER BY p.name) FILTER (WHERE cs.slug = ANY(%(c)s)) AS shared_programmes
    FROM programs p JOIN program_tags pt ON pt.program_id = p.id JOIN tags t ON t.id = pt.tag_id {_CLAUSE_JOIN}
    WHERE p.funder_id IS NOT NULL GROUP BY p.funder_id
)
SELECT f.id, f.name, f.slug, f.funder_type, pl.shared_districts, pl.shared_states, pl.pan_india, pl.regions,
    pl.stated_places, pl.observed_places, fc.tag_clauses, fc.asserted_tag_clauses, fc.shared_tag_clauses,
    pr.tagged_programmes, pr.asserted_programmes, pr.shared_programmes
FROM funders f
LEFT JOIN places pl ON pl.funder_id = f.id
LEFT JOIN funder_clauses fc ON fc.funder_id = f.id
LEFT JOIN programmes pr ON pr.funder_id = f.id
ORDER BY f.id
"""


def _fit(r: dict) -> PairFit:
    return PairFit(
        shared_districts=tuple(r["shared_districts"] or ()), shared_states=tuple(r["shared_states"] or ()),
        pan_india=bool(r["pan_india"]), regions=tuple(r["regions"] or ()),
        stated_places=r["stated_places"] or 0, observed_places=r["observed_places"] or 0,
        tag_clauses=tuple(r["tag_clauses"] or ()), asserted_tag_clauses=tuple(r["asserted_tag_clauses"] or ()),
        shared_tag_clauses=tuple(r["shared_tag_clauses"] or ()), tagged_programmes=r["tagged_programmes"] or 0,
        asserted_programmes=r["asserted_programmes"] or 0, shared_programmes=tuple(r["shared_programmes"] or ()))


async def load_fit(conn: Any, org: OrgEvidence) -> dict[int, FunderEvidence]:
    """Stage 1: one row per funder saying what it shares with `org`."""
    rows = await _rows(conn, FIT_SQL, {"d": list(org.districts), "s": list(org.states), "c": list(org.clauses)})
    return {r["id"]: FunderEvidence(FunderRef(id=r["id"], name=r["name"], slug=r["slug"],
                                              funder_type=r["funder_type"]), _fit(r)) for r in rows}


async def enrich_funders(conn: Any, funders: dict[int, FunderEvidence], reads) -> None:
    """Stage 2 for the funders stage 1 kept: one query per funder-side kind, never per funder."""
    _refuse_unknown(reads, "funder.", FUNDER_KINDS)

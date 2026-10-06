"""The one home for match judgements. The CLI, the agent's tools and the evals all call these."""

from __future__ import annotations

from typing import Any, Literal

from app.matching import registry
from app.matching.config import Criteria
from app.matching.engine import assess as assess_pair
from app.matching.engine import rank_key
from app.matching.evaluators import REGISTRY
from app.matching.evidence import enrich_funders, load_fit, load_org
from app.matching.models import Ambiguous, Assessment, Resolved, Shortlist

CriteriaRef = str | int
ACTIVE = registry.ACTIVE
_TABLES = {"org": "orgs", "funder": "funders"}


def reads_for(criteria: Criteria) -> set[str]:
    return {k for c in criteria.checks for k in REGISTRY[c.evaluator].reads}


async def _assess_all(conn: Any, org_id: int, ref: CriteriaRef):
    loaded = await registry.get(conn, registry.SET_NAME, ref)
    reads = reads_for(loaded.criteria)
    org = await load_org(conn, org_id, reads)
    funders = await load_fit(conn, org)
    await enrich_funders(conn, funders, reads)
    return loaded, org, [assess_pair(loaded.criteria, org, f, criteria_hash=loaded.content_hash)
                         for f in funders.values()]


async def shortlist(conn: Any, org_id: int, *, criteria: CriteriaRef = ACTIVE,
                    limit: int = 20, offset: int = 0) -> Shortlist:
    """Every funder judged for one org: ranked, not enough recorded, or did not pass (R12)."""
    loaded, org, assessed = await _assess_all(conn, org_id, criteria)
    has_fit = "fit" in loaded.criteria.groups
    ranked, thin, failed = [], [], []
    for a in sorted(assessed, key=lambda a: rank_key(a, loaded.criteria.ranking)):
        if a.gate_status == "failed":
            failed.append(a)
        elif has_fit and a.fit_status == "unknown":
            thin.append(a.funder)
        else:
            ranked.append(a)
    return Shortlist(criteria_version=loaded.version, criteria_hash=loaded.content_hash, org=org.org,
                     ranked=ranked[offset:offset + limit], not_enough_recorded=sorted(thin, key=lambda f: f.id),
                     did_not_pass=failed, total_funders=len(assessed), offset=offset, limit=limit)


async def assess_many(conn: Any, org_id: int, funder_ids: list[int], *,
                      criteria: CriteriaRef = ACTIVE) -> list[Assessment]:
    """Assessments in the order the ids were given; an unknown id raises LookupError."""
    _, _, assessed = await _assess_all(conn, org_id, criteria)
    by_id = {a.funder.id: a for a in assessed}
    missing = [i for i in funder_ids if i not in by_id]
    if missing:
        raise LookupError(f"funder not found: {missing}")
    return [by_id[i] for i in funder_ids]


async def assess(conn: Any, org_id: int, funder_id: int, *, criteria: CriteriaRef = ACTIVE) -> Assessment:
    return (await assess_many(conn, org_id, [funder_id], criteria=criteria))[0]


async def resolve(conn: Any, kind: Literal["org", "funder"], text: str) -> Resolved | Ambiguous:
    """An id, slug or exact name gives one; otherwise substring, then trigram, candidates."""
    table, text = _TABLES[kind], text.strip()

    async def rows(where: str, params: tuple, order: str = "id") -> list[Resolved]:
        found = await (await conn.execute(
            f"SELECT id, name, slug FROM {table} WHERE {where} ORDER BY {order} LIMIT 10", params)).fetchall()
        return [Resolved(kind=kind, **r) for r in found]

    exact = await rows("id::text = %s OR lower(slug) = lower(%s) OR lower(name) = lower(%s)", (text,) * 3)
    if len(exact) == 1:
        return exact[0]
    like = exact or await rows("name ILIKE %s OR slug ILIKE %s", (f"%{text}%",) * 2)
    if len(like) == 1:
        return like[0]
    near = like or await rows("similarity(name, %s) > 0.3 OR similarity(slug, %s) > 0.3", (text,) * 4,
                              order="greatest(similarity(name, %s), similarity(slug, %s)) DESC, id")
    return Ambiguous(kind=kind, text=text, candidates=near)

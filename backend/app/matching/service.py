"""One saved run: every funder judged for one org, written as the run's writer. The route and make match share it."""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool

from app.matching.assessment import Match
from app.matching.match import match
from app.matching.rubric import RUBRIC_VERSION
from app.repositories import funder_matches, matching


def rows(matches: list[Match]) -> list[dict]:
    """The spec's funder_matches row and funder_match_details detail for each match."""
    out = []
    for m in matches:
        scored = m.score is not None
        out.append({
            "funder_id": m.funder_id,
            "score": m.score["of_100"] if scored else None,
            "card": {"reasons": [r.model_dump() for r in m.card]},
            "detail": {
                "summary": m.summary,
                "criteria": [c.model_dump() for c in m.criteria] if scored else [],
                "score": m.score,
                "not_judged": m.not_judged if scored else [],
                "improve": m.improve,
            },
        })
    return out


async def run_and_save(reader: AsyncConnectionPool, writer: Any, org_id: int, run_by: UUID | None) -> dict:
    """Read as the owner, so every runner judges the same inputs; write as `writer`, under its RLS."""
    org, funders, places = await matching.load(reader, org_id, None)
    if org is None:
        raise LookupError(f"no organisation with id {org_id}")
    matches = [match(org, f, places) for f in funders]
    saved = await funder_matches.insert_run(writer, org_id, uuid4(), run_by, RUBRIC_VERSION, rows(matches))
    tiers = Counter(m.tier for m in matches)
    return {**saved, "org_id": org_id, "rubric_version": RUBRIC_VERSION, "funders_checked": len(matches),
            "tiers": {t: tiers.get(t, 0) for t in ("strong", "medium", "weak", "not_scored")}}

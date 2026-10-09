"""compare_fit: an organisation against funders, judged and scored in code under match-v1."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from app.agent.assessment import Match
from app.agent.match import match
from app.agent.rubric import RUBRIC_VERSION
from app.agent.rules import FunderProfile, OrgProfile, Places, has_places_or_themes
from app.core.config import get_settings
from app.db.pool import get_pool
from app.repositories import matching


def _entry(m: Match) -> dict:
    return {
        "funder": f"{m.funder_name} [funder:{m.funder_id}]",
        "funder_type": m.funder_type,
        "score": m.score["of_100"] if m.score else None,
        "tier": m.tier,
        "judged": f"{m.score['earned']} of {m.score['judged_max']} points" if m.score else None,
        "card": [f"{'✓' if r.kind == 'fit' else '!'} {r.text}" for r in m.card],
        "summary": m.summary,
        "criteria": [
            {"criterion": c.label, "points": f"{c.points}/{c.max}" if c.points is not None else "unknown",
             "status": c.status, "note": c.note, "cites": c.cites}
            for c in m.criteria
        ],
        "not_judged": m.not_judged,
        "improve": m.improve,
    }


def compare(org: OrgProfile, funders: list[FunderProfile], places: Places, *, shortlist: bool) -> dict:
    matches = [match(org, f, places) for f in funders]
    has_data = {f.id: has_places_or_themes(f) for f in funders}
    shown = [m for m in matches if m.score or not shortlist]
    shown.sort(key=lambda m: (m.score is None, -(m.score or {}).get("of_100", 0), m.funder_id))
    unscored = [m for m in matches if m.score is None and shortlist]
    return {
        "org": f"{org.name} [org:{org.id}]",
        "rubric": RUBRIC_VERSION,
        "funders_checked": len(funders),
        "matches": [_entry(m) for m in shown],
        "not_scored": {
            # Recorded on both sides with nothing shared: a real non-fit.
            "nothing_in_common_recorded": [f"{m.funder_name} [funder:{m.funder_id}]"
                                           for m in unscored if has_data[m.funder_id]],
            # The funder has no places or themes recorded: unknown, never a non-fit.
            "funder_has_nothing_recorded": [f"{m.funder_name} [funder:{m.funder_id}]"
                                            for m in unscored if not has_data[m.funder_id]],
        },
    }


@tool
async def compare_fit(org_id: int, funder_ids: list[int] | None = None) -> str:
    """Score one organisation against funders under the match-v1 rubric, from the database, in one call.

    Args:
        org_id: the organisation's id (resolve the name with db_query first).
        funder_ids: the funders to score. Omit it to check every funder: those sharing a place or
            a theme are scored, the rest are listed under not_scored.

    Returns JSON: `matches`, ranked by score (out of 100, highest first; null last), each with its
    tier (strong >= 75, medium 55-74, weak < 55, not_scored), card lines (✓ fit, ! gap), summary,
    the seven criteria (theme 25, geography 15, population 15, eligibility 20, relationship 10,
    funding size 10, capacity 5) with points, status, note and cites, `not_judged` and `improve`.
    An unknown criterion is left out of the score, never counted as zero. `not_scored` names the
    funders with nothing in common recorded and those with nothing recorded at all. Every figure is
    computed in code from recorded rows: repeat it, never recompute or re-judge it.
    """
    try:
        org, funders, places = await matching.load(
            get_pool(), org_id, funder_ids, timeout_ms=get_settings().sql_timeout_ms
        )
        if org is None:
            return f"compare_fit failed: no organisation with id {org_id}"
        if funder_ids and (missing := sorted(set(funder_ids) - {f.id for f in funders})):
            return f"compare_fit failed: no funder with id {', '.join(map(str, missing))}"
        return json.dumps(compare(org, funders, places, shortlist=funder_ids is None), default=str, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - errors are return values: a raise aborts the run
        return f"compare_fit failed: {exc}"

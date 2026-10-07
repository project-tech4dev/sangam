"""compare_fit: an organisation against funders, judged and scored in code from two profiles."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from app.agent.assessment import Check, FunderAssessment
from app.agent.rules import FunderProfile, OrgProfile, Places, has_places_or_themes, judge_org, judge_pair
from app.core.config import get_settings
from app.db.pool import get_pool
from app.repositories import matching

GAP = {
    "reg_12a": "record the 12A registration", "reg_80g": "record the 80G registration",
    "csr_1": "record the CSR-1 registration", "darpan": "record the NGO Darpan ID", "pan": "record the PAN",
    "reg_no": "record the registration number", "fcra": "record the FCRA registration",
    "audits_3y": "upload three years of audited accounts", "itr_7": "upload the income tax returns (ITR-7)",
    "board": "record three office bearers", "team_cvs": "upload team CVs",
    "projects_3": "record three completed projects with funder, amount, theme, duration and results",
    "area": "record where the funder gives and where the organisation works",
    "theme": "record the sector themes on both sides", "programme": "tag the organisation's programmes with themes",
    "funder_bar": "review the funder's eligibility criterion",
}


def _gaps(checks: list[Check]) -> list[str]:
    # A fail first: it closes a gate. Then what is not recorded.
    failed = [f"{GAP[c.code]} ({c.note})" for c in checks if c.outcome == "fail"]
    return list(dict.fromkeys([*failed, *(GAP[c.code] for c in checks if c.outcome == "unknown")]))


def _short(c: Check) -> dict:
    return {k: v for k, v in c.model_dump().items() if v not in (None, "", [])}


def _assess(org: OrgProfile, readiness: list[Check], funder: FunderProfile, places: Places) -> FunderAssessment:
    pair = judge_pair(org, funder, places)
    return FunderAssessment(
        org_id=org.id, funder_id=funder.id, funder_name=funder.name, funder_type=funder.funder_type,
        section_135_bound=funder.section_135_bound, foreign_funder=pair.foreign_funder,
        shared_districts=pair.shared_districts, reasons=pair.reasons,
        checks=[*pair.checks, *readiness], gaps=_gaps(pair.checks),
    )


def _is_candidate(a: FunderAssessment, funder: FunderProfile) -> bool:
    fit = {c.code: c.outcome for c in a.checks if c.code in ("area", "theme", "programme")}
    # An unrecorded region can neither match nor rule out a place, so it stays in.
    return "met" in fit.values() or (fit["area"] == "unknown" and bool(funder.location_ids))


def compare(org: OrgProfile, funders: list[FunderProfile], places: Places, *, shortlist: bool) -> dict:
    readiness = judge_org(org)
    assessed, nothing_in_common, nothing_recorded = [], 0, []
    for funder in funders:
        a = _assess(org, readiness, funder, places)
        if not shortlist or _is_candidate(a, funder):
            assessed.append(a)
        elif has_places_or_themes(funder):
            nothing_in_common += 1
        else:
            nothing_recorded.append(f"{funder.name} [funder:{funder.id}]")
    assessed.sort(key=lambda a: a.rank_key)
    pair_codes = {"area", "theme", "programme", "turnover", "funder_bar"}
    return {
        "org": f"{org.name} [org:{org.id}]",
        "funders_considered": len(funders),
        "readiness": [_short(c) for c in readiness],
        "assessed": [
            {
                **a.model_dump(include={"funder_id", "funder_name", "funder_type", "section_135_bound",
                                        "shared_districts", "reasons", "gaps"}),
                "cite": f"[funder:{a.funder_id}]",
                "gate": a.gate, "gate_reasons": a.gate_reasons, "score": a.score,
                "breakdown": a.breakdown, "coverage": a.coverage, "rank_key": a.rank_key,
                "checks": [_short(c) for c in a.checks if c.code in pair_codes],
            }
            for a in assessed
        ],
        "not_assessed": {"nothing_in_common_recorded": nothing_in_common, "nothing_recorded": nothing_recorded},
        "what_to_record": _gaps(readiness),
    }


@tool
async def compare_fit(org_id: int, funder_ids: list[int] | None = None) -> str:
    """Judge and score one organisation against funders, from the database, in one call.

    Args:
        org_id: the organisation's id (resolve the name with db_query first).
        funder_ids: the funders to judge. Omit it to consider every funder: those sharing a
            place or a theme are assessed, the rest are counted under not_assessed.

    Returns JSON: `readiness` (the organisation's own twelve checks, the same for every funder),
    `assessed` (one entry per funder, sorted by rank_key, each with gate, gate_reasons, score
    out of 100, breakdown, coverage, its place/theme/programme checks, cited reasons and gaps),
    `not_assessed` counts, and `what_to_record` for the organisation. Every check is computed in
    code from recorded rows: met, fail, or unknown (not recorded). Repeat it; never recompute it.
    """
    try:
        org, funders, places = await matching.load(
            get_pool(), org_id, funder_ids, timeout_ms=get_settings().sql_timeout_ms
        )
        if org is None:
            return f"compare_fit failed: no organisation with id {org_id}"
        if funder_ids and (missing := sorted(set(funder_ids) - {f.id for f in funders})):
            return f"compare_fit failed: no funder with id {', '.join(map(str, missing))}"
        return json.dumps(compare(org, funders, places, shortlist=funder_ids is None), default=str)
    except Exception as exc:  # noqa: BLE001 - errors are return values: a raise aborts the run
        return f"compare_fit failed: {exc}"

"""Turns check results into a decision: three-valued groups, gates, a weighted score range, a rank."""

from __future__ import annotations

from app.matching.config import Criteria
from app.matching.evaluators import run
from app.matching.evidence import FunderEvidence, OrgEvidence
from app.matching.models import Assessment, CategoryScore, CheckResult, Outcome

_GATE_ORDER = {"passed": 0, "unverified": 1, "failed": 2}
_ROLE_ORDER = {"gate": 0, "weighted": 1, "advisory": 2, "none": 3}
_OUTCOME_ORDER = {"fail": 0, "unknown": 1, "met": 2}


def combine(form: dict, outcomes: list[Outcome]) -> Outcome:
    """Kleene logic: unknown only where the known members cannot settle it."""
    met, fail = outcomes.count("met"), outcomes.count("fail")
    unknown = len(outcomes) - met - fail
    if "all" in form:
        return "fail" if fail else "unknown" if unknown else "met"
    if "any" in form:
        return "met" if met else "unknown" if unknown else "fail"
    need = form["min_met"]
    return "met" if met >= need else "fail" if met + unknown < need else "unknown"


def _round(x: float) -> int:
    return int(x + 0.5)


def _containers(criteria: Criteria) -> dict[str, set[str]]:
    """Every group that contains each code, transitively."""
    parents: dict[str, set[str]] = {}
    for name, g in criteria.groups.items():
        for m in g.members:
            parents.setdefault(m, set()).add(name)
    out: dict[str, set[str]] = {}
    for code in [c.code for c in criteria.checks] + list(criteria.groups):
        seen, stack = set(), list(parents.get(code, ()))
        while stack:
            p = stack.pop()
            if p not in seen:
                seen.add(p)
                stack.extend(parents.get(p, ()))
        out[code] = seen
    return out


def _selected(selector: dict, funder: FunderEvidence) -> bool:
    if "always" in selector:
        return bool(selector["always"])
    # An unrecorded type keeps the check: skipping it would read "type unknown" as a pass.
    return funder.funder.funder_type is None or funder.funder.funder_type in selector["funder_type"]


def assess(criteria: Criteria, org: OrgEvidence, funder: FunderEvidence, *, criteria_hash: str = "") -> Assessment:
    containers = _containers(criteria)

    def applies(code: str) -> bool:
        return all(_selected(criteria.applies[c], funder)
                   for c in {code, *containers[code]} if c in criteria.applies)

    gate_members = {m for g in criteria.roles.gate for m in {g, *_descendants(criteria, g)}}
    advisory_members = {m for g in criteria.roles.advisory for m in {g, *_descendants(criteria, g)}}

    results: dict[str, CheckResult] = {}
    for chk in criteria.checks:
        cat = criteria.category_of(chk.code)
        role = ("gate" if chk.code in gate_members else "weighted" if cat
                else "advisory" if chk.code in advisory_members else "none")
        group = next((g for g, d in criteria.groups.items() if chk.code in d.members), None)
        common = {"code": chk.code, "label": chk.label, "group": group, "role": role,
                  "category": cat[0] if cat else None, "weight": cat[1] if cat else 0}
        if not applies(chk.code):
            results[chk.code] = CheckResult(**common, outcome="unknown", basis="not_applicable",
                                            reason_code="not_applicable")
            continue
        c = run(chk.evaluator, org, funder, chk.params)
        results[chk.code] = CheckResult(**common, outcome=c.outcome, basis=c.basis, level=c.level,
                                        reason_code=c.reason_code, reason_params=c.reason_params,
                                        cites=list(c.cites))

    def outcome(code: str) -> Outcome | None:
        """None when the code does not apply to this funder."""
        if not applies(code):
            return None
        if code in results:
            return results[code].outcome
        g = criteria.groups[code]
        members = [o for o in (outcome(m) for m in g.members) if o is not None]
        form = {"all": True} if g.all_ is not None else {"any": True} if g.any_ is not None else {"min_met": g.min_met}
        return combine(form, members) if members else None

    gates = {g: outcome(g) for g in criteria.roles.gate}
    failed = [g for g, o in gates.items() if o == "fail"]
    gate_status = "failed" if failed else "unverified" if "unknown" in gates.values() else "passed"

    breakdown: dict[str, CategoryScore] = {}
    earned = unknown_w = applicable = 0.0
    for name, cat in criteria.weights.items():
        e = u = a = 0.0
        for code, w in cat.checks.items():
            r = results[code]
            if r.basis == "not_applicable":
                continue
            a += w
            if r.outcome == "met":
                e += w * criteria.partial.get(code, {}).get(r.level, 1.0) if r.level else w
            elif r.outcome == "unknown":
                u += w
        breakdown[name] = CategoryScore(earned=round(e, 2), unknown=u, applicable=int(a))
        earned, unknown_w, applicable = earned + e, unknown_w + u, applicable + a
    if applicable:
        score_min = _round(100 * earned / applicable)
        score_max = _round(100 * (earned + unknown_w) / applicable)
        coverage = _round(100 * (applicable - unknown_w) / applicable)
    else:
        score_min, score_max, coverage = 0, 100, 0

    order = {c.code: i for i, c in enumerate(criteria.checks)}
    open_ = [r for r in results.values() if r.basis != "not_applicable" and r.outcome != "met"]
    gaps = sorted((r for r in open_ if r.role != "advisory"),
                  key=lambda r: (_ROLE_ORDER[r.role], -r.weight, _OUTCOME_ORDER[r.outcome], order[r.code]))
    cites = sorted({c for r in results.values() if r.outcome != "unknown" for c in r.cites}
                   | {org.cite, funder.cite})
    return Assessment(
        criteria_version=criteria.version, criteria_hash=criteria_hash, org=org.org, funder=funder.funder,
        gate_status=gate_status, fit_status=(outcome("fit") if "fit" in criteria.groups else None) or "unknown",
        failed_gates=failed, checks=list(results.values()), score_min=score_min, score_max=score_max,
        coverage=coverage, breakdown=breakdown, shared_districts=len(funder.fit.shared_districts),
        gaps=gaps, advisory_gaps=[r for r in open_ if r.role == "advisory"], citations=cites,
    )


def _descendants(criteria: Criteria, code: str) -> set[str]:
    if code not in criteria.groups:
        return set()
    out: set[str] = set()
    for m in criteria.groups[code].members:
        out |= {m, *_descendants(criteria, m)}
    return out


def rank_key(a: Assessment, keys: list[str]) -> tuple:
    parts = {
        "gate_status": _GATE_ORDER[a.gate_status],
        "score_min": -a.score_min,
        "score_max": -a.score_max,
        "coverage": -a.coverage,
        "shared_districts": -a.shared_districts,
        "funder_id": a.funder.id,
    }
    return tuple(parts[k] for k in keys)

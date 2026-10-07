"""Gate, score and order from the matching checks. rules.py judges each check; this only does arithmetic.

Pure: no pool, no async, no settings. Takes plain (code, outcome, level) tuples so it never imports assessment.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Gate = Literal["pass", "unverified", "fail"]
Fact = tuple[str, str, "str | None"]

# group -> (points, checks). A dict gives each check its own points; a tuple splits them equally.
WEIGHTS: dict[str, tuple[int, dict[str, int] | tuple[str, ...]]] = {
    "fit": (40, {"area": 20, "theme": 12, "programme": 8}),
    "compliance": (25, ("reg_12a", "reg_80g", "csr_1", "darpan", "pan", "reg_no", "fcra")),
    "financial": (15, ("audits_3y", "itr_7", "turnover")),
    "governance": (10, ("board", "team_cvs")),
    "programme": (10, ("projects_3",)),
}
# Share of the area points each level earns: a local match beats a broad one.
AREA_CREDIT = {"district": 1.0, "state": 0.6, "pan_india": 0.3, "regional": 0.3}

FIT = ("area", "theme", "programme")
STATUTORY = ("reg_12a", "reg_80g", "csr_1", "audits_3y")
# CSR money routed through a company's foundation still needs a CSR-1 registered implementer.
STATUTORY_FUNDER_TYPES = frozenset({"corporate_csr", "corporate_foundation"})
UNTYPED = frozenset({None, "", "other"})
# Scored only when returned: only some funders record a turnover bar.
CONDITIONAL = frozenset({"turnover"})

_GATE_RANK = {"pass": 0, "unverified": 1, "fail": 2}


@dataclass(frozen=True)
class Result:
    gate: Gate
    gate_reasons: list[str]
    score: int
    breakdown: dict[str, float]
    coverage: float
    rank_key: str


def _statutory_applies(funder_type: str | None, section_135_bound: bool | None) -> bool | None:
    """True / False, or None when nobody has recorded what kind of funder this is."""
    if funder_type in STATUTORY_FUNDER_TYPES or section_135_bound is True:
        return True
    if funder_type in UNTYPED and section_135_bound is None:
        return None
    return False


def _gates(outcome: dict[str, str], bars: list[str], statutory: bool | None) -> tuple[Gate, list[str]]:
    failed: list[str] = []
    open_: list[str] = []

    fit = [outcome.get(c, "unknown") for c in FIT]
    if "met" not in fit:
        if all(o == "fail" for o in fit):
            failed.append("fit: no shared area, theme or programme recorded")
        else:
            open_.append("fit: nothing shared confirmed yet")

    if statutory is None:
        open_.append("statutory: funder type not recorded, so whether 12A/80G/CSR-1/audits apply is unknown")
    elif statutory:
        got = {c: outcome.get(c, "unknown") for c in STATUTORY}
        if bad := [c for c, o in got.items() if o == "fail"]:
            failed.append(f"statutory: {', '.join(bad)} failed")
        elif missing := [c for c, o in got.items() if o != "met"]:
            open_.append(f"statutory: {', '.join(missing)} not recorded")

    if "turnover" in outcome:
        if outcome["turnover"] == "fail":
            failed.append("turnover: below the funder's bar")
        elif outcome["turnover"] != "met":
            open_.append("turnover: not recorded")

    if "fail" in bars:
        failed.append("funder bar: a recorded eligibility bar is not met")
    elif any(o != "met" for o in bars):
        open_.append("funder bar: not every recorded bar is confirmed")

    if failed:
        return "fail", failed + open_
    return ("unverified" if open_ else "pass"), open_


def evaluate(
    facts: Iterable[Fact],
    *,
    funder_type: str | None,
    section_135_bound: bool | None,
    foreign_funder: bool | None = None,
    shared_districts: int,
    funder_id: int,
) -> Result:
    facts = list(facts)
    outcome = {code: o for code, o, _ in facts if code != "funder_bar"}
    level = {code: lv for code, _, lv in facts}
    bars = [o for code, o, _ in facts if code == "funder_bar"]
    statutory = _statutory_applies(funder_type, section_135_bound)

    gate, reasons = _gates(outcome, bars, statutory)

    breakdown: dict[str, float] = {}
    applicable = known = 0
    for group, (points, checks) in WEIGHTS.items():
        shares = checks if isinstance(checks, dict) else dict.fromkeys(checks, 1)
        live = {
            c: s for c, s in shares.items()
            if not (c in CONDITIONAL and c not in outcome)
            and not (c == "csr_1" and statutory is False)
            # FCRA governs foreign money only; readiness returns it for every funder.
            and not (c == "fcra" and foreign_funder is not True)
        }
        total = sum(live.values())
        earned = 0.0
        for c, share in live.items():
            o = outcome.get(c, "unknown")
            applicable += 1
            known += o != "unknown"
            if o == "met":
                earned += share * (AREA_CREDIT.get(level.get(c) or "", 0.0) if c == "area" else 1.0)
        breakdown[group] = round(points * earned / total, 1) if total else 0.0

    score = round(sum(breakdown.values()))
    coverage = round(known / applicable, 2) if applicable else 0.0
    # Ascending sort = gate, then score, coverage and shared districts high-first, then funder_id.
    rank_key = (
        f"{_GATE_RANK[gate]}-{100 - score:03d}-{100 - round(coverage * 100):03d}"
        f"-{999 - min(shared_districts, 999):03d}-{funder_id:08d}"
    )
    return Result(gate, reasons, score, breakdown, coverage, rank_key)

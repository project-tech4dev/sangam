"""One pair under match-v1: the criteria from rules.py, then the card, summary and actions from templates."""

from __future__ import annotations

from datetime import date

from app.matching import rubric
from app.matching.assessment import Match, Reason
from app.matching.rules import Finding, FunderProfile, OrgProfile, Places, judge

TIER_WORDS = {"strong": "A strong fit", "medium": "A medium fit", "weak": "A weak fit"}


def _card(findings: list[Finding], scored: bool) -> list[Reason]:
    if not scored:
        return [Reason(kind="gap", criterion="overlap", text="No shared place or theme recorded")]
    judged = [f for f in findings if f.criterion.points is not None]
    fits = sorted((f for f in judged if f.criterion.status == "met"), key=lambda f: -f.criterion.points)[:2]
    lost = sorted((f for f in judged if f.criterion.status in ("partial", "fail")),
                  key=lambda f: f.criterion.points - f.criterion.max)[:2]
    return [*(Reason(kind="fit", criterion=f.criterion.code, text=f.line) for f in fits),
            *(Reason(kind="gap", criterion=f.criterion.code, text=f.line) for f in lost)]


def _summary(m: Match, org: OrgProfile) -> str:
    if m.score is None:
        return (f"Not scored. No place or theme in common is recorded between {org.name} and {m.funder_name}, "
                "so there was nothing to judge.")
    s = m.score
    out = [f"{TIER_WORDS[m.tier]} at {s['of_100']}/100 ({s['earned']} of {s['judged_max']} judged points)."]
    if fits := [c.label.lower() for c in m.criteria if c.status == "met"]:
        out.append(f"It fits on {', '.join(fits)}.")
    if lost := [f"{c.label.lower()} ({c.max - c.points} of {c.max})" for c in m.criteria
                if c.status in ("partial", "fail")]:
        out.append(f"Points are lost on {', '.join(lost)}.")
    if unknown := [c.label.lower() for c in m.criteria if c.status == "unknown"]:
        out.append(f"Not judged, so left out rather than scored as zero: {', '.join(unknown)}.")
    return " ".join(out)


def match(org: OrgProfile, funder: FunderProfile, places: Places, *, today: date | None = None) -> Match:
    findings = judge(org, funder, places, today=today)
    criteria = [f.criterion for f in findings]
    scored = rubric.score({c.code: c.points for c in criteria}) is not None
    not_judged = [f"{c.label}: {c.note}." for c in criteria if c.points is None]
    not_judged += [n for f in findings for n in f.not_judged]
    m = Match(
        org_id=org.id, funder_id=funder.id, funder_name=funder.name, funder_type=funder.funder_type,
        criteria=criteria, card=_card(findings, scored), summary="", not_judged=not_judged,
        improve=[i for f in findings for i in f.improve] if scored else [],
    )
    m.summary = _summary(m, org)
    return m

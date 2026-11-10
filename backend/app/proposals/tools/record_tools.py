"""What Sangam already holds about the proposal's org and its fit with the funder. Public rows only, every one cited."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from app.db.pool import get_pool
from app.proposals import context
from app.repositories import profile_facts
from app.repositories import proposals as repo

logger = logging.getLogger(__name__)

TEXT = 400  # a description longer than this is cut; the record holds it whole
ROWS = 12   # programmes, places and funding lines listed, each


def _cut(text: str | None) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= TEXT else f"{text[:TEXT]}…"


def _money(value: float | None) -> str:
    if value is None:
        return "not public"
    return f"₹{value / 1e7:.2f} crore" if value >= 1e7 else f"₹{value / 1e5:.2f} lakh"


def match_text(match: dict[str, Any]) -> str:
    detail = match.get("detail") or {}
    marker = f"[score:{match['id']}]"
    lines = [f"Funder Match {marker}, saved {str(match['run_at'])[:10]}: {detail.get('summary') or ''}"]
    for c in detail.get("criteria") or []:
        points = "not judged" if c.get("points") is None else f"{c['points']} of {c['max']}"
        lines.append(f"- {c['label']}: {points}, {c['status']}. {c.get('note') or ''} {' '.join(c.get('cites') or [])}")
    if detail.get("not_judged"):
        lines += ["Not judged:", *[f"- {line}" for line in detail["not_judged"]]]
    if detail.get("improve"):
        lines += ["What would raise the score:", *[f"- {line}" for line in detail["improve"]]]
    return "\n".join(lines)


@tool
async def read_match() -> str:
    """Read the saved Funder Match this proposal started from: the score, each criterion with its points and
    note, and what would raise the score. Cited [score:N]."""
    try:
        p = await context.current()
        if p is None:
            return "No proposal is open in this chat."
        match = await repo.match_for(get_pool(), p.org_id, p.funder_id)
        if match is None or match["id"] != (p.work.get("match") or {}).get("id"):
            saved = p.work.get("match") or {}
            note = "" if match is None else " A newer run exists; this proposal keeps the one it started from."
            return f"The saved match [score:{saved.get('id')}] scored {saved.get('score')}/100.{note}"
        return match_text(match)
    except Exception as exc:
        logger.exception("read_match failed")
        return f"read_match failed: {type(exc).__name__}"


def org_text(facts: Any) -> str:
    """The org's public record in lines, each with its marker; registrations without their numbers."""
    org = facts.org
    o = f"[org:{org.id}]"
    lines = [f"{org.name} {o}" + "".join(f" · {v}" for v in (org.legal_form, org.district, org.state) if v)]
    if org.registration_date:
        lines.append(f"Registered {org.registration_date} {o}")
    if org.staff_count:
        lines.append(f"Staff: {org.staff_count}{' (' + org.staff_count_note + ')' if org.staff_count_note else ''} {o}")
    if org.website:
        lines.append(f"Website: {org.website} {o}")
    if org.description:
        lines.append(f"About: {_cut(org.description)} {o}")
    if org.identifiers:
        lines.append("Registrations: " + "; ".join(
            f"{i.id_type} {i.status}" + (f" until {i.valid_until}" if i.valid_until else "") for i in org.identifiers)
            + f" {o}")
    if facts.places:
        lines.append("Works in: " + "; ".join(
            f"{pl.name}{', ' + pl.state if pl.state else ''}" for pl in facts.places[:ROWS]) + f" {o}")
    for fy in facts.financials[:3]:
        lines.append(f"FY {fy.fiscal_year}: income {_money(fy.total_income)}, programmes {_money(fy.program_spend)}"
                     f"{', audited' if fy.is_audited else ''} {o}")
    for prog in facts.programs[:ROWS]:
        dates = f" ({prog.start_date or '?'} to {prog.end_date or 'now'})" if prog.start_date or prog.end_date else ""
        lines.append(f"Programme: {prog.name}{dates}. {_cut(prog.description)} {o}")
        for m in prog.metrics[:4]:
            lines.append(f"  - {m.name}: {m.value if m.value is not None else '?'} {m.unit or ''}"
                         f"{' (' + m.period + ')' if m.period else ''} {o}")
    for group in facts.funders.groups[:ROWS]:
        for line in group.lines[:3]:
            lines.append(f"Funded by {line.funder_name}, FY {line.fiscal_year}: {line.project_name or 'a grant'}, "
                         f"{_money(line.amount)} [activity:{line.id}]")
    return "\n".join(lines)


@tool
async def read_org_record() -> str:
    """Read what Sangam's registry holds about this proposal's organisation: identity, registrations (no numbers),
    places, recent finances, programmes with their figures, and past funding. Public rows only. Cited [org:N] and
    [activity:N]."""
    try:
        p = await context.current()
        if p is None:
            return "No proposal is open in this chat."
        facts = await profile_facts.org_facts(get_pool(), get_pool(), str(p.org_id))
        if facts is None:
            return f"Sangam holds no record for {p.org_name}."
        return org_text(facts)
    except Exception as exc:
        logger.exception("read_org_record failed")
        return f"read_org_record failed: {type(exc).__name__}"

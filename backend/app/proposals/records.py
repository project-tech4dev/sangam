"""The org's record and its Funder Match as cited lines, and the check that a registry fact's value appears in the row
its marker names, re-read with the same fixed SQL the read tools use."""

from __future__ import annotations

from typing import Any

from app.proposals import facts as fact_rules
from app.repositories import profile_facts
from app.repositories import proposals as repo

TEXT = 400  # a description longer than this is cut; the record holds it whole
ROWS = 12   # programmes, places and funding lines listed, each
_DISTRICTS: set[str] = set()


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


async def districts(pool: Any) -> set[str]:
    """Every district Sangam knows, read once: the trace check needs only their names."""
    if not _DISTRICTS:
        async with pool.connection() as conn:
            rows = await (await conn.execute("SELECT DISTINCT lower(name) AS name FROM locations WHERE kind = 'district'"
                                             )).fetchall()
        # A three-letter district (Mon, Una, Leh) reads as an ordinary word too often to check.
        _DISTRICTS.update(n for r in rows if r["name"] and len(n := " ".join(r["name"].replace("-", " ").split())) > 3)
    return _DISTRICTS


async def _lines(pool: Any, p: Any, marker: str) -> list[str] | str:
    kind, _, number = marker.strip("[]").partition(":")
    if kind == "score":
        if int(number) != (p.work.get("match") or {}).get("id"):
            return f"{marker} is not the Funder Match this proposal started from"
        match = await repo.match_for(pool, p.org_id, p.funder_id)
        if match is None or match["id"] != int(number):
            return f"{marker} is no longer held"
        text = match_text(match)
    else:
        if kind == "org" and int(number) != p.org_id:
            return f"{marker} is not {p.org_name}"
        held = await profile_facts.org_facts(pool, pool, str(p.org_id))
        if held is None:
            return f"Sangam holds no record for {p.org_name}"
        text = org_text(held)
    lines = [line for line in text.splitlines() if marker in line]
    return lines or f"{marker} is not in {p.org_name}'s record"


def appears(value: str, lines: list[str]) -> bool:
    """Every number in the value is in the row ("₹2.4 crore" in "₹2.40 crore"); text with no number, as words."""
    held = " ".join(lines)
    wanted = fact_rules.numbers(value)
    if wanted:
        have = fact_rules.numbers(held)
        return all(any(abs(w - h) < 0.005 for h in have) for w in wanted)
    return fact_rules.norm(value) in fact_rules.norm(held)


async def check(pool: Any, p: Any, fact: dict[str, Any]) -> str | None:
    """Why a registry fact is refused, or None."""
    lines = await _lines(pool, p, fact["marker"])
    if isinstance(lines, str):
        return f"{fact['subject']}: {lines}"
    if not appears(fact["value"], lines):
        return f"{fact['subject']}: {fact['value']!r} is not what {fact['marker']} says"
    return None

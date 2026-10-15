"""A registry fact's value must appear in the row its marker names, re-read with the same fixed SQL the read tools use."""

from __future__ import annotations

from typing import Any

from app.proposals import facts as fact_rules
from app.repositories import profile_facts
from app.repositories import proposals as repo


async def _lines(pool: Any, p: Any, marker: str) -> list[str] | str:
    from app.proposals.tools.record_tools import match_text, org_text

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

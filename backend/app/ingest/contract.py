"""The researcher's contract, checked in code: every field answered, and what was quoted extracted."""

from __future__ import annotations

import re
from typing import Any

from app.ingest.expectations import concepts_for, expected_fields, recent_fiscal_years
from app.ingest.research_records import YEARLY, EntityResearch

# Identity fields every complete save answers; a note or a timestamp is not a field of its own.
_IDENTITY = {"identity", "org_identity"}
_NOT_ASKED = {"as_of", "tag_note", "staff_count_note"}
# A comma counts only between digits, so "In 2023, across" reads the year alone.
_NUMBER = re.compile(r"(?<![\w.])\d(?:\d|,(?=\d))*(?:\.\d+)?")
_FISCAL = re.compile(r"\d{4}\s*[-–]\s*\d{2,4}")
_SHOWN = 15


def _filled(value: Any) -> bool:
    return value not in (None, "", [], {})


def unanswered(research: EntityResearch) -> list[str]:
    """What a save reporting findings leaves with neither a finding nor a gap; not_found and wrong_entity have none."""
    if research.status not in ("complete", "partial") or research.entity_kind == "unknown":
        return []
    findings, gaps = research.findings, research.gaps
    years = research.years or list(recent_fiscal_years())
    missing: list[str] = []
    for concept in concepts_for(research.entity_kind):
        found = [f for f in findings if f.concept == concept]
        gapped = [g for g in gaps if g.concept == concept]
        if not found and not gapped:
            missing.append(f"{concept}: no finding and no gap")
            continue
        if concept in YEARLY and not any(g.fiscal_year is None and g.field is None for g in gapped):
            for year in years:
                if not any(f.fiscal_year == year for f in found) and not any(g.fiscal_year == year for g in gapped):
                    missing.append(f"{concept} {year}: no finding and no gap")
        if concept in _IDENTITY and found:
            fields = [e.name for e in expected_fields(concept) if e.name not in _NOT_ASKED] + ["themes"]
            for name in fields:
                if not any(_filled(getattr(f, name, None)) for f in found) and not any(g.field == name for g in gapped):
                    missing.append(f"{concept}.{name}: no value and no gap")
    return missing


def _numbers(value: Any, out: set[float]) -> None:
    """Every number a structured field carries, including those inside names and notes."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.add(round(float(value), 2))
    elif isinstance(value, str):
        out.update(_parse(m) for m in _NUMBER.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            _numbers(v, out)
    elif isinstance(value, list):
        for v in value:
            _numbers(v, out)


def _parse(text: str) -> float:
    return round(float(text.replace(",", "")), 2)


def quoted_only(research: EntityResearch) -> list[str]:
    """Numbers a finding's quote states that no field of the save carries, e.g. '23,686 villages'."""
    carried: set[float] = set()
    for f in research.findings:
        _numbers({k: v for k, v in f.model_dump().items() if k not in ("evidence", "source_url", "page")}, carried)
    for u in research.unplaced:
        _numbers(u.value, carried)
    out: list[str] = []
    seen: set[float] = set()
    for f in research.findings:
        text = _FISCAL.sub(" ", f.evidence)
        for m in _NUMBER.finditer(text):
            n = _parse(m.group())
            is_year = n.is_integer() and 1900 <= n <= 2100 and "," not in m.group()
            if n < 10 or is_year or n in carried or n in seen:
                continue
            seen.add(n)
            words = text[max(0, m.start() - 30): m.end() + 30].split()
            out.append(f"'{m.group()}' in a {f.concept} quote: …{' '.join(words)}…")
    return out[:_SHOWN]

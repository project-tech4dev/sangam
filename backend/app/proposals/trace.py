"""The trace check: every number, place and name in a paragraph is in a fact that paragraph cites. Pure.

Shared with polish (M6), so it only reads text and facts; the tool loads the district names it is given.
"""

from __future__ import annotations

import re
from typing import Any

from app.ingest.geography import canonical_state
from app.proposals import facts as fact_rules

CITE = re.compile(r"⟦(k\d+)⟧")
GAP = re.compile(r"\[Add:[^\]]*\]")
_UNITS = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7}
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(lakhs?|lac|crores?|cr)\b")
# Years, financial-year ranges and Schedule VII clauses are dates and labels, not claims.
_SKIP = re.compile(
    r"\bfy\s*\d{2,4}(?:\s*[-–/]\s*\d{2,4})?"
    r"|\b(?:19|20)\d{2}\s*[-–/]\s*\d{2,4}\b"
    r"|\b(?:19|20)\d{2}\b"
    r"|schedule\s+vii(?:\s*[,(]?\s*(?:clause|item)?\s*\(?[ivx\d]+\)?)?"
    r"|\b(?:clause|item)\s*\(?[ivx\d]+\)?"
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
TOLERANCE = 0.005  # "₹2.4 crore" against "₹2,40,00,000": equal within rounding of the printed figure


def paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def cited(text: str) -> list[str]:
    return list(dict.fromkeys(CITE.findall(text or "")))


def _claims(text: str) -> tuple[list[float], list[float]]:
    """The paragraph's plain numbers, and its amounts in rupees; markers, gaps, years and clauses dropped."""
    body = _SKIP.sub(" ", fact_rules.norm(GAP.sub(" ", CITE.sub(" ", text))))
    amounts = [float(n) * _UNITS[u] for n, u in _AMOUNT.findall(body)]
    return [float(n) for n in _NUMBER.findall(_AMOUNT.sub(" ", body))], amounts


def _values(facts: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    """Every number a fact states, and each also read as rupees when a unit follows it."""
    numbers: list[float] = []
    amounts: list[float] = []
    for f in facts:
        text = fact_rules.norm(f"{f.get('value')} {f.get('evidence') or ''}")
        numbers += [float(n) for n in _NUMBER.findall(text)]
        amounts += [float(n) * _UNITS[u] for n, u in _AMOUNT.findall(text)]
    return numbers, amounts


def _held(n: float, pool: list[float]) -> bool:
    return any(abs(n - v) <= max(abs(v) * TOLERANCE, 1e-9) for v in pool)


def _words(text: str) -> str:
    return f" {re.sub(r'[^a-z0-9]+', ' ', fact_rules.norm(text))} "


def _places(text: str, districts: set[str]) -> list[str]:
    """States and known districts named in the text, as written there."""
    words = _words(GAP.sub(" ", text))
    found = [name for name in districts if f" {name} " in words]
    tokens = words.split()
    for size in (3, 2, 1):
        for i in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[i:i + size])
            if canonical_state(phrase) and not any(phrase in f for f in found):
                found.append(phrase)
    return found


def check(text: str, facts: dict[str, dict[str, Any]], *, districts: set[str] = frozenset(),
          names: set[str] = frozenset()) -> list[str]:
    """Why this text cannot be saved, paragraph by paragraph; empty means every claim traces to a cited fact.

    `districts` are lower-case district names; `names` the partner and people names the fact list holds."""
    problems: list[str] = []
    for i, para in enumerate(paragraphs(text), start=1):
        ids = cited(para)
        missing = [k for k in ids if k not in facts]
        dead = [k for k in ids if k in facts and not fact_rules.is_live(facts[k])]
        if missing:
            problems.append(f"paragraph {i} cites {', '.join(missing)}, which the fact list does not hold")
        if dead:
            problems.append(f"paragraph {i} cites {', '.join(dead)}, which the person set aside or corrected")
        held = [facts[k] for k in ids if k in facts and fact_rules.is_live(facts[k])]
        numbers, amounts = _values(held)
        haystack = _words(" ".join(f"{f.get('subject')} {f.get('value')} {f.get('evidence') or ''}" for f in held))
        says, rupees = _claims(para)
        for n in says:
            if not _held(n, numbers):
                problems.append(f"paragraph {i}: {n:g} is in no fact it cites")
        for r in rupees:
            if not (_held(r, amounts) or _held(r, numbers)):
                problems.append(f"paragraph {i}: ₹{r:,.0f} is in no fact it cites")
        for place in _places(para, districts):
            if f" {place} " not in haystack:
                problems.append(f"paragraph {i}: {place.title()} is in no fact it cites")
        for name in names:
            if f" {name} " in _words(GAP.sub(" ", para)) and f" {name} " not in haystack:
                problems.append(f"paragraph {i}: {name.title()} is in no fact it cites")
    return problems

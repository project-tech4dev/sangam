"""match-v1: the criteria, their points and the arithmetic. rules.py judges; this only counts.

Pure: no pool, no async, no settings, no pydantic.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Literal

RUBRIC_VERSION = "match-v1"

Status = Literal["met", "partial", "fail", "unknown"]
Tier = Literal["strong", "medium", "weak", "not_scored"]

# code -> (label, max points), in the order every match is read.
CRITERIA: dict[str, tuple[str, int]] = {
    "theme": ("Theme alignment", 25),
    "geography": ("Geography", 15),
    "population": ("Target population", 15),
    "eligibility": ("Eligibility & compliance", 20),
    "relationship": ("Relationship", 10),
    "funding_size": ("Funding size", 10),
    "capacity": ("Funder capacity", 5),
}
# Without a shared place or theme there is nothing to score on.
OVERLAP = ("theme", "geography")

MET_SHARE = 0.8
STRONG, MEDIUM = 75, 55

THEME_NO_PROGRAMME = 15
GEOGRAPHY = {"district": 15, "state": 12, "india": 6, "region": 6}
RELATIONSHIP_UNCONFIRMED = 5
FUNDING_STRETCH = 2  # a smallest grant up to this many times the org's income is partial
FUNDING_PARTIAL = 5
CAPACITY_YEARS = 3
CAPACITY_PARTIAL = 3


def maximum(code: str) -> int:
    return CRITERIA[code][1]


def status_for(points: int | None, max_points: int) -> Status:
    if points is None:
        return "unknown"
    if points >= MET_SHARE * max_points:
        return "met"
    return "partial" if points > 0 else "fail"


def score(points: Mapping[str, int | None]) -> dict[str, int] | None:
    """earned, judged_max and of_100; None when no place or theme is shared. Unknown is left out, never zero."""
    if not any(points.get(c) for c in OVERLAP):
        return None
    judged = {c: p for c, p in points.items() if p is not None}
    earned, judged_max = sum(judged.values()), sum(maximum(c) for c in judged)
    return {"earned": earned, "judged_max": judged_max, "of_100": round(100 * earned / judged_max)}


def tier(of_100: int | None) -> Tier:
    if of_100 is None:
        return "not_scored"
    return "strong" if of_100 >= STRONG else "medium" if of_100 >= MEDIUM else "weak"


def fy_start(text: str | None) -> int | None:
    """'FY2023-24' -> 2023."""
    m = re.search(r"(\d{4})", text or "")
    return int(m.group(1)) if m else None


def current_fy(today: date) -> int:
    # India's fiscal year starts on 1 April.
    return today.year if today.month >= 4 else today.year - 1


def capacity_window(today: date) -> range:
    """The last CAPACITY_YEARS completed fiscal years, as start years."""
    now = current_fy(today)
    return range(now - CAPACITY_YEARS, now)

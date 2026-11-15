"""Dropdown options for a list screen, from counts its SQL made. Pure."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from app.schemas.common import Facet


def ordered(counts: Counter, numeric: bool = False) -> list[Facet]:
    """Most common first, ties A→Z ignoring case; `numeric` options (SDGs) in number order instead."""
    return [Facet(value=v, count=counts[v]) for v in sorted(counts, key=_order(counts, numeric))]


def _order(counts: Counter, numeric: bool) -> Callable[[str], tuple]:
    if numeric:
        return lambda v: (int(v) if v.isdigit() else float("inf"), v)
    return lambda v: (-counts[v], v.casefold(), v)

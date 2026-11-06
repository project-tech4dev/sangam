"""Bucket counts and dropdown options for a list screen, counted over its rows. Pure."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.schemas.common import Facet


@dataclass(frozen=True)
class FacetSpec:
    name: str
    values: Callable[[dict], Iterable[str]]  # a row's values for this dropdown; each counted once a row
    numeric: bool = False                     # options in number order (SDGs), not most common first


def count_by(rows: Iterable[dict], key: str) -> dict[str, int]:
    """{"all": rows, <each value of key>: rows with it}, for the bucket cards."""
    rows = list(rows)
    return {"all": len(rows), **Counter(str(r[key]) for r in rows)}


def count_facets(rows: Iterable[dict], specs: Iterable[FacetSpec]) -> dict[str, list[Facet]]:
    """Each dropdown's options with how many rows have them: most common first, ties A→Z."""
    rows, out = list(rows), {}
    for spec in specs:
        out[spec.name] = ordered(Counter(v for r in rows for v in {str(v) for v in spec.values(r) if v}), spec.numeric)
    return out


def ordered(counts: Counter, numeric: bool = False) -> list[Facet]:
    """Options counted elsewhere (in SQL), in the order count_facets gives them."""
    return [Facet(value=v, count=counts[v]) for v in sorted(counts, key=_order(counts, numeric))]


def _order(counts: Counter, numeric: bool) -> Callable[[str], tuple]:
    if numeric:
        return lambda v: (int(v) if v.isdigit() else float("inf"), v)
    return lambda v: (-counts[v], v.casefold(), v)

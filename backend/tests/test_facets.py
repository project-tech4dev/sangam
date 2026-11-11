"""Dropdown options, in the order the Registry's browser code gave them."""

from __future__ import annotations

from collections import Counter

from app.repositories.facets import ordered
from app.schemas.common import FacetedPage


def test_options_go_most_common_first_then_alphabetical_ignoring_case():
    states = ordered(Counter({"Goa": 1, "Assam": 2, "goa": 1, "Bihar": 1}))
    assert [(f.value, f.count) for f in states] == [("Assam", 2), ("Bihar", 1), ("Goa", 1), ("goa", 1)]


def test_numeric_options_keep_number_order():
    sdgs = ordered(Counter({"10": 2, "3": 2, "2": 1}), numeric=True)
    assert [(f.value, f.count) for f in sdgs] == [("2", 1), ("3", 2), ("10", 2)]


def test_a_faceted_page_carries_the_page_with_its_counts_and_options():
    page = FacetedPage[dict](items=[{"id": 1}], total=9, limit=1, offset=0, counts={"all": 9},
                             facets={"where": ordered(Counter({"Assam": 2, "Goa": 1}))})
    out = page.model_dump()
    assert set(out) == {"items", "total", "limit", "offset", "counts", "facets"}
    assert out["facets"]["where"][0] == {"value": "Assam", "count": 2}
    assert FacetedPage[dict](items=[], total=0, limit=25, offset=0).model_dump()["facets"] == {}

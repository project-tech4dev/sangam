"""Bucket counts and dropdown options, counted the way the Registry's browser code counted them."""

from __future__ import annotations

from app.repositories.facets import FacetSpec, count_by, count_facets
from app.schemas.common import FacetedPage

ROWS = [
    {"kind": "org", "states": ["Assam", "Goa"], "sdgs": ["10", "3"]},
    {"kind": "org", "states": ["Assam", "Assam"], "sdgs": ["3"]},
    {"kind": "org", "states": ["goa"], "sdgs": ["2"]},
    {"kind": "funder", "states": ["Bihar"], "sdgs": []},
    {"kind": "funder", "states": [], "sdgs": ["10"]},
]


def test_count_by_counts_every_row_and_each_kind():
    assert count_by(ROWS, "kind") == {"all": 5, "org": 3, "funder": 2}
    assert count_by([], "kind") == {"all": 0}


def test_options_go_most_common_first_then_alphabetical_and_count_a_row_once():
    states = count_facets(ROWS, [FacetSpec("where", lambda r: r["states"])])["where"]
    # Assam twice in one row still counts that row once; ties sort A→Z ignoring case.
    assert [(f.value, f.count) for f in states] == [("Assam", 2), ("Bihar", 1), ("Goa", 1), ("goa", 1)]


def test_numeric_options_keep_number_order():
    sdgs = count_facets(ROWS, [FacetSpec("sdg", lambda r: r["sdgs"], numeric=True)])["sdg"]
    assert [(f.value, f.count) for f in sdgs] == [("2", 1), ("3", 2), ("10", 2)]


def test_empty_values_are_not_options():
    out = count_facets([{"t": None}, {"t": ""}, {"t": "x"}], [FacetSpec("t", lambda r: [r["t"]])])
    assert [(f.value, f.count) for f in out["t"]] == [("x", 1)]


def test_a_faceted_page_carries_the_page_with_its_counts_and_options():
    page = FacetedPage[dict](items=[{"id": 1}], total=9, limit=1, offset=0, counts={"all": 9},
                             facets=count_facets(ROWS, [FacetSpec("where", lambda r: r["states"])]))
    out = page.model_dump()
    assert set(out) == {"items", "total", "limit", "offset", "counts", "facets"}
    assert out["facets"]["where"][0] == {"value": "Assam", "count": 2}
    assert FacetedPage[dict](items=[], total=0, limit=25, offset=0).model_dump()["facets"] == {}

"""The Registry's filters in Python, case for case with frontend/features/registry/__tests__/rows.test.ts."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from app.repositories.registry import NORTH_EAST, Filters, matches

ALL = Filters()


def row(**over) -> dict:
    return {"kind": "org", "id": 1, "slug": "kabil", "name": "KABIL Trust", "funder_type": None, "states": [],
            "themes": [], "populations": [], "sdgs": [], "csr1": False, "has_12a_80g": False, "fcra": False,
            "intake_mode": None, "open_call": False, "search": "", **over}


def test_passes_everything_on_the_defaults():
    assert matches(row(), ALL)


def test_filters_by_kind_theme_population_and_sdg():
    r = row(themes=[{"label": "Maternal health", "domain": "Health"}], populations=["women"], sdgs=["3"])
    assert not matches(r, replace(ALL, kind="funder"))
    assert matches(r, replace(ALL, kind="org", theme="Health", population="women", sdg="3"))
    assert not matches(r, replace(ALL, theme="Education"))
    assert not matches(r, replace(ALL, population="youth"))
    assert not matches(r, replace(ALL, sdg="4"))


def test_reads_where_as_the_north_east_outside_it_or_one_state():
    assam, goa = row(states=["Assam"]), row(states=["Goa"])
    assert matches(assam, replace(ALL, where="ne"))
    assert not matches(goa, replace(ALL, where="ne"))
    assert matches(goa, replace(ALL, where="out"))
    assert not matches(assam, replace(ALL, where="out"))
    assert matches(goa, replace(ALL, where="Goa"))
    assert not matches(goa, replace(ALL, where="Assam"))


def test_applies_registrations_only_to_organisations():
    org = replace(ALL, kind="org")
    assert matches(row(csr1=True), replace(org, reg="csr1"))
    assert not matches(row(), replace(org, reg="csr1"))
    assert not matches(row(), replace(org, reg="12a80g"))
    assert matches(row(has_12a_80g=True), replace(org, reg="12a80g"))
    assert not matches(row(), replace(org, reg="fcra"))
    assert matches(row(), replace(ALL, reg="fcra"))


def test_applies_funder_type_and_approach_only_to_funders():
    funder = replace(ALL, kind="funder")
    f = row(kind="funder", funder_type="government", open_call=True)
    assert matches(f, replace(funder, ftype="government", approach="open"))
    assert not matches(f, replace(funder, ftype="bilateral"))
    assert not matches(f, replace(funder, approach="invites"))
    assert not matches(row(kind="funder"), replace(funder, approach="open"))
    assert matches(row(kind="funder", intake_mode="invitation_only"), replace(funder, approach="invites"))
    assert matches(row(), replace(ALL, ftype="bilateral"))


def test_searches_the_search_text_and_the_name_ignoring_case_and_spaces():
    r = row(name="Tata Trusts", search="mumbai water")
    assert matches(r, replace(ALL, q="  TATA "))
    assert matches(r, replace(ALL, q="water"))
    assert not matches(r, replace(ALL, q="goa"))


def test_search_finds_a_match_inside_a_word():
    assert matches(row(search="udalguri assam"), replace(ALL, q="dalgu"))


def test_north_east_matches_the_frontend_list():
    rows_ts = Path(__file__).resolve().parents[2] / "frontend/features/registry/rows.ts"
    if not rows_ts.exists():
        pytest.skip("frontend not checked out")
    block = re.search(r"NORTH_EAST = \[(.*?)\]", rows_ts.read_text(), re.DOTALL)
    assert tuple(re.findall(r'"([^"]+)"', block.group(1))) == NORTH_EAST

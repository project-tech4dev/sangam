"""match-v1 arithmetic: unknown is left out, never zero; no shared place or theme is no score."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.agent import rubric
from app.agent.assessment import Criterion

SPEC_EXAMPLE = {
    "theme": 22, "geography": 12, "population": 13, "eligibility": 14,
    "relationship": 0, "funding_size": None, "capacity": 5,
}


def test_the_specs_worked_example_scores_66_of_90_as_73():
    assert rubric.score(SPEC_EXAMPLE) == {"earned": 66, "judged_max": 90, "of_100": 73}


def test_an_unknown_criterion_is_left_out_not_scored_zero():
    points = dict.fromkeys(rubric.CRITERIA, None) | {"theme": 25}
    assert rubric.score(points) == {"earned": 25, "judged_max": 25, "of_100": 100}


@pytest.mark.parametrize("overlap", [{"theme": None, "geography": None}, {"theme": 0, "geography": 0}])
def test_no_shared_place_or_theme_is_no_score(overlap):
    assert rubric.score(SPEC_EXAMPLE | overlap) is None


@pytest.mark.parametrize(("of_100", "tier"), [
    (75, "strong"), (74, "medium"), (55, "medium"), (54, "weak"), (0, "weak"), (None, "not_scored"),
])
def test_tier_thresholds(of_100, tier):
    assert rubric.tier(of_100) == tier


@pytest.mark.parametrize(("points", "status"), [(15, "met"), (12, "met"), (11, "partial"), (0, "fail"), (None, "unknown")])
def test_status_comes_from_points(points, status):
    assert rubric.status_for(points, 15) == status


def test_fiscal_years_parse_and_the_window_is_the_last_three_completed():
    assert rubric.fy_start("FY2023-24") == 2023
    assert rubric.fy_start(None) is None
    assert list(rubric.capacity_window(date(2026, 10, 10))) == [2023, 2024, 2025]
    assert list(rubric.capacity_window(date(2026, 3, 31))) == [2022, 2023, 2024]


def test_a_judged_criterion_must_cite_except_an_absent_relationship():
    with pytest.raises(ValidationError):
        Criterion(code="theme", points=25, note="shared", cites=[])
    assert Criterion(code="relationship", points=0, note="none recorded").status == "fail"
    with pytest.raises(ValidationError):
        Criterion(code="capacity", points=6, note="too many", cites=["[activity:1]"])

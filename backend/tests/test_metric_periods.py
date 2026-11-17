"""A metric's period in one of four shapes (#200), and a programme's start derived from its year (#199)."""

from __future__ import annotations

from datetime import date
from importlib.resources import files

import pytest
from pydantic import ValidationError

from app.ingest import brief
from app.ingest.catalog.promote_records import validated
from app.ingest.catalog.rows import shape_period
from app.ingest.catalog.writer import period_end
from app.ingest.research.finding_types import MetricFinding, ProgramFinding

SRC = "https://example.org/annual-report.pdf"


def metric(**kw):
    return {"concept": "metric", "name": "teachers trained", "value": 12400,
            "evidence": "In FY2023-24, we trained 12,400 teachers across 9 districts of Assam.",
            "source_url": SRC, "confidence": "high", **kw}


@pytest.mark.parametrize("text, shaped", [
    ("FY2024-25", "FY2024-25"),
    ("FY 2024-25", "FY2024-25"),
    ("fy2024-2025", "FY2024-25"),
    ("FY1999-00", "FY1999-00"),
    ("FY 2024–25", "FY2024-25"),
    ("FY 2024 - 25", "FY2024-25"),
    ("CY2025", "CY2025"),
    ("calendar year 2024", "CY2024"),
    ("Calendar year 2025 (Geschäftsjahr 2025)", "CY2025"),
    ("cumulative to 2025-03-31", "cumulative to 2025-03-31"),
    ("cumulative to March 2025", "cumulative to 2025-03-31"),
    ("cumulative to February 2024", "cumulative to 2024-02-29"),
    ("cumulative to December 2024", "cumulative to 2024-12-31"),
    ("cumulative to FY2022-23", "cumulative to 2023-03-31"),
    ("as of 31 March 2026", "as of 2026-03-31"),
    ("as on 31 Mar 2026", "as of 2026-03-31"),
    ("As of  2025-09-30", "as of 2025-09-30"),
])
def test_a_period_that_maps_exactly_is_rewritten(text, shaped):
    assert shape_period(text) == shaped


@pytest.mark.parametrize("text", [
    "2024", "2024-25", "FY2024-26", "current (c. 2025-26)", "cumulative since 2013", "GROW 2022-24",
    "undated website figure ('2,000+')", "calendar year 2025 (FY2025-26)", "as of 31 Febtember 2025",
])
def test_a_period_that_does_not_map_exactly_is_not_guessed(text):
    assert shape_period(text) is None


class TestASaveTakesOnlyTheFourShapes:
    def test_a_shaped_period_is_saved_in_its_shape(self):
        assert MetricFinding(**metric(period="calendar year 2024")).period == "CY2024"

    def test_a_bare_range_is_refused_with_the_shapes(self):
        with pytest.raises(ValidationError, match="cumulative to 2025-03-31"):
            MetricFinding(**metric(period="2024-25"))

    def test_no_period_stays_null(self):
        assert MetricFinding(**metric()).period is None


class TestResearchSavedBeforeIsNeverRefused:
    def test_an_old_period_is_rewritten_when_exact_and_kept_otherwise(self):
        report = {"held": []}
        out = validated([metric(period="cumulative to March 2025"), metric(name="schools", period="since 2013")],
                        "metric", report)
        assert [m.period for m in out] == ["cumulative to 2025-03-31", "since 2013"]
        assert report["held"] == []

    def test_the_brief_counts_two_spellings_of_one_period_as_one_fact(self):
        assert brief.fact_key(metric(period="calendar year 2024")) == brief.fact_key(metric(period="CY2024"))
        assert brief.fact_key(metric(period="since 2013")) != brief.fact_key(metric(period="undated"))


@pytest.mark.parametrize("as_of, end", [
    ("FY2023-24", "2024-03-31"), ("CY2024", "2024-12-31"),
    ("cumulative to 2025-03-31", "2025-03-31"), ("as of 2025-09-30", "2025-09-30"), ("since 2013", None),
    ("FY 2024-25", "2025-03-31"), ("as on 31 March 2025", "2025-03-31"),
])
def test_a_shaped_period_is_comparable_by_its_end(as_of, end):
    assert period_end(as_of) == end


def programme(**kw):
    return {"name": "Promoting Livelihoods for Rural Poor Households - Mazbat Block",
            "evidence": "Mazbat Block livelihoods programme, an FY2024-25 line item in the annual report.",
            "source_url": SRC, "confidence": "high", **kw}


class TestAProgrammeStartsOnTheFirstDayOfItsYear:
    def test_a_fiscal_year_programme_saves_its_derived_1_april_start(self):
        p = ProgramFinding(**programme(start_date="2024-04-01", basis="derived"))
        assert (p.start_date, p.basis) == (date(2024, 4, 1), "derived")

    def test_the_researcher_is_told_the_rule(self):
        prompt = (files("app.ingest") / "prompts" / "entity_researcher.md").read_text(encoding="utf-8")
        assert "that year's 1 April, with `basis` `derived`" in prompt
        assert "1 April" in ProgramFinding.model_fields["start_date"].description

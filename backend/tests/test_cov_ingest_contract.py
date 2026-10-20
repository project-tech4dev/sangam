"""The researcher's contract: every field answered, and every quoted number carried by a field."""

from __future__ import annotations

import pytest

from app.ingest.contract import _numbers, quoted_only, unanswered
from app.ingest.expectations import concepts_for
from app.ingest.research_records import YEARLY, EntityResearch

URL = "https://example.org/csr-report.pdf"
SUMMARY = "Example Foundation funds sports and water projects in Assam."


def gap(concept: str, **over) -> dict:
    return {"concept": concept, "reason": "not_stated", "detail": "the annual report does not say", **over}


def research(findings=(), gaps=(), **over) -> EntityResearch:
    return EntityResearch.model_validate({
        "entity_name": "Example Foundation", "entity_kind": "funder", "status": "partial",
        "stopped_reason": "Stopped at the reading limit.", "summary": SUMMARY,
        "findings": list(findings), "gaps": list(gaps), **over,
    })


def spend(year="FY2023-24", evidence="The company spent Rs 6.74 crore on sports in FY2023-24.", **over) -> dict:
    return {"concept": "csr_spend", "fiscal_year": year, "project_name": "Sports scholarships",
            "amount": {"value": 6.74, "unit": "crore", "text": "Rs 6.74 crore"}, "domain": "others",
            "classified_by": "project_name", "confidence": "medium", "source_url": URL,
            "evidence": evidence, **over}


def every_concept_gapped(kind="funder", skip=()) -> list[dict]:
    return [gap(c) for c in concepts_for(kind) if c not in skip]


class TestUnanswered:
    def test_not_found_and_wrong_entity_answer_nothing(self):
        r = EntityResearch(entity_name="Acme", entity_kind="funder", status="not_found", summary=SUMMARY)
        assert unanswered(r) == []

    def test_an_empty_partial_save_names_every_concept(self):
        missing = unanswered(research())
        assert {m.split(":")[0] for m in missing} == set(concepts_for("funder"))

    def test_a_concept_wide_gap_answers_every_year(self):
        assert unanswered(research(gaps=every_concept_gapped())) == []

    def test_a_yearly_finding_must_cover_each_year_asked(self):
        years = ["FY2023-24", "FY2022-23"]
        r = research(findings=[spend()], gaps=every_concept_gapped(skip={"csr_spend"}), years=years)
        assert unanswered(r) == ["csr_spend FY2022-23: no finding and no gap"]

    def test_a_year_gap_answers_that_year(self):
        years = ["FY2023-24", "FY2022-23"]
        r = research(findings=[spend()], years=years,
                     gaps=[*every_concept_gapped(skip={"csr_spend"}), gap("csr_spend", fiscal_year="FY2022-23")])
        assert unanswered(r) == []

    def test_an_identity_finding_lists_each_field_without_a_value_or_gap(self):
        identity = {"concept": "identity", "name": "Example Foundation", "confidence": "high",
                    "source_url": URL, "evidence": "Example Foundation is a Section 8 company in Assam."}
        r = research(findings=[identity], gaps=every_concept_gapped(skip={"identity"}))
        missing = unanswered(r)
        assert "identity.website: no value and no gap" in missing
        assert "identity.themes: no value and no gap" in missing
        assert not any(m.startswith("identity.name") or "as_of" in m or "tag_note" in m for m in missing)

    def test_a_field_gap_answers_that_field(self):
        identity = {"concept": "identity", "name": "Example Foundation", "website": "https://example.org",
                    "confidence": "high", "source_url": URL,
                    "evidence": "Example Foundation is a Section 8 company in Assam."}
        r = research(findings=[identity], gaps=every_concept_gapped(skip={"identity"}))
        before = unanswered(r)
        assert "identity.website: no value and no gap" not in before
        r2 = research(findings=[identity], gaps=[*every_concept_gapped(skip={"identity"}),
                                                 gap("identity", field="cin")])
        assert "identity.cin: no value and no gap" in before
        assert "identity.cin: no value and no gap" not in unanswered(r2)

    def test_yearly_set_is_what_the_check_walks(self):
        assert "csr_spend" in YEARLY and "identity" not in YEARLY


class TestQuotedOnly:
    def test_a_number_carried_by_a_field_is_not_flagged(self):
        assert quoted_only(research(findings=[spend()])) == []

    def test_a_number_only_in_the_quote_is_flagged_with_context(self):
        r = research(findings=[spend(evidence="Rs 6.74 crore reached 23,686 villages across Assam in FY2023-24.")])
        [line] = quoted_only(r)
        assert line.startswith("'23,686' in a csr_spend quote:") and "villages" in line

    def test_years_small_numbers_and_fiscal_years_are_ignored(self):
        r = research(findings=[spend(evidence="In 2023 across 5 districts, Rs 6.74 crore was spent (2023-24).")])
        assert quoted_only(r) == []

    @pytest.mark.xfail(strict=True, reason="_NUMBER takes the comma after '2023,' so the year check misses it")
    def test_a_year_before_a_comma_is_still_a_year(self):
        r = research(findings=[spend(evidence="In 2023, across 5 districts, Rs 6.74 crore was spent.")])
        assert quoted_only(r) == []

    def test_a_number_is_flagged_once(self):
        f1 = spend(evidence="Rs 6.74 crore reached 4,200 children in FY2023-24 alone.")
        f2 = spend(year="FY2022-23", evidence="Again 4,200 children were reached, Rs 6.74 crore.")
        assert len(quoted_only(research(findings=[f1, f2]))) == 1

    def test_unplaced_values_count_as_carried(self):
        r = research(findings=[spend(evidence="Rs 6.74 crore reached 23,686 villages across Assam.")],
                     unplaced=[{"field": "villages", "value": "23,686", "source_url": URL,
                                "evidence": "Rs 6.74 crore reached 23,686 villages across Assam."}])
        assert quoted_only(r) == []

    def test_at_most_fifteen_lines(self):
        quote = "Counts: " + ", ".join(str(100 + i) for i in range(20)) + " in all."
        assert len(quoted_only(research(findings=[spend(evidence=quote)]))) == 15


class TestNumbers:
    def test_walks_nested_values_and_skips_bools(self):
        out: set[float] = set()
        _numbers({"a": [1, "2,500 kids", {"b": 3.14159}], "flag": True, "none": None}, out)
        assert out == {1.0, 2500.0, 3.14}

"""Expected vs pulled: cells by year, gap reasons, the printed table and what a save stores."""

from __future__ import annotations

from app.ingest import coverage as cov

FUNDER = {
    "slug": "acme", "canonical_name": "Acme", "entity_kind": "funder",
    "goals": ["csr for FY2024-25 and FY2023-24"],
    "findings": [
        {"concept": "csr_year", "fiscal_year": "FY2024-25", "total_spent": 1},
        {"concept": "csr_year", "fiscal_year": "FY2019-20", "total_spent": 2},
        {"concept": "program", "name": "Swasthya", "themes": []},
        {"concept": "program", "description": "nameless", "themes": ["skilling"]},
        {"concept": "rfp", "title": "Call"},
    ],
    "gaps": [
        {"concept": "csr_year", "fiscal_year": "FY2023-24", "reason": "blocked", "detail": "403"},
        {"concept": "csr_spend", "reason": "not_reached", "detail": "ran out"},
        {"concept": "identity", "field": "website", "reason": "not_stated"},
    ],
}


def by_concept(c):
    return {line.concept: line for line in c.lines}


class TestCompute:
    def test_cells_years_and_reasons(self):
        c = cov.compute(FUNDER, report={"skipped": {"rfp": 1}, "held": ["partner: bad", "partner x"]})
        assert c.years == ["FY2024-25", "FY2023-24"] and c.write_checked
        lines = by_concept(c)
        assert [x.status for x in lines["csr_year"].cells] == ["found", "blocked"]
        assert lines["csr_year"].extra_years == ["FY2019-20"]
        assert {x.status for x in lines["csr_spend"].cells} == {"not_attempted"}
        assert lines["csr_spend"].cells[0].detail == "ran out"
        assert lines["identity"].cells[0].status == "not_attempted"  # a field gap never explains a missing cell
        assert lines["rfp"].cells[0].status == "not_written" and lines["rfp"].cells[0].detail == "no catalog writer"
        assert lines["partner"].held == 2
        assert lines["program"].untagged == ["Swasthya"] and lines["program"].programmes == 2
        assert lines["program"].fields_filled == 3  # name, description, themes

    def test_not_found_stands_in_for_gaps_and_unknown_kind_uses_every_concept(self):
        c = cov.compute({"entity_name": "x", "findings": "bad", "gaps": "bad", "not_found": ["contact"]},
                        years=["FY2024-25"])
        assert c.kind == "unknown" and c.entity == "x" and not c.write_checked
        assert by_concept(c)["contact"].cells[0].status == "not_stated"
        assert len(c.lines) == len(cov.CONCEPTS)

    def test_default_years(self):
        assert cov.compute({"entity_kind": "org"}).years == sorted(cov.recent_fiscal_years(), reverse=True)


class TestRender:
    def test_table(self):
        text = cov.render(cov.compute(FUNDER, report={"skipped": {"rfp": 1}, "held": ["partner: x"]}))
        lines = text.splitlines()
        assert lines[0] == "Coverage: Acme (funder), FY2023-24 to FY2024-25"
        assert lines[1].startswith("Concepts 2/")  # the rfp was found but not written
        assert "found, not written 1" in lines[2]
        csr = next(x for x in lines if x.startswith("csr_year"))
        assert "1/2" in csr and "FY2023-24 blocked: 403" in csr and "also found FY2019-20 (not asked)" in csr
        assert "1 line(s) held back" in next(x for x in lines if x.startswith("partner"))
        assert "1 of 2 programmes have no theme: Swasthya" in next(x for x in lines if x.startswith("program "))
        assert next(x for x in lines if x.startswith("program ")).split()[1] == "✓"
        assert next(x for x in lines if x.startswith("rfp")).split()[1] == "–"
        assert "Found, not written" not in text

    def test_ngo_note_and_single_year(self):
        text = cov.render(cov.compute({"entity_kind": "org", "canonical_name": "N"}, years=["FY2024-25"]))
        assert text.startswith("Coverage: N (org), FY2024-25") and "cannot be dry-run" in text
        assert "Concepts 0/" in text

    def test_pct_of_nothing(self):
        assert cov._pct(0, 0) == "–"
        assert cov.render(cov.Coverage("e", "k", [], [], True)).startswith("Coverage: e (k), \nConcepts 0/0 (–)")


REPORT = {
    "entity": {"kind": "funder", "status": "updated"},
    "csr_years": [{"status": "added"}, {"status": "same"}],
    "written": {"programs": {"added": 2, "updated": 1, "same": 4}, "unknown table": {"added": 9}},
    "held": ["x"], "skipped": {"rfp": 1}, "reasons": ["r"], "conflicts": [],
}


class TestChanges:
    def test_changes_by_concept(self):
        assert cov.changes_by_concept(REPORT) == {"identity": {"added": 0, "updated": 1},
                                                  "csr_year": {"added": 1, "updated": 0},
                                                  "program": {"added": 2, "updated": 1}}
        assert cov.changes_by_concept({"entity": {"kind": "org", "status": "added"}}) == {
            "org_identity": {"added": 1, "updated": 0}}

    def test_saved_record(self):
        assert cov.saved_record({"changes": {}}, {"entity": {"kind": "org"}}, None) is None
        assert cov.saved_record(None, {}, None) is None
        first = cov.saved_record(None, REPORT, {"program": 5, "contact": 1})
        assert first["rows_before"] == {"program": 3, "contact": 1} and first["skipped"] == {"rfp": 1}
        again = cov.saved_record(first, REPORT, {"program": 7})
        assert again["changes"]["program"] == {"added": 4, "updated": 2}
        assert again["rows_before"] == first["rows_before"]

    def test_view(self):
        row = {**FUNDER, "saved_at": "t"}
        out = cov.view(row, stage="saved", report=None, entity={"id": 1}, reasons=[], held=[], questions=2,
                       changes={"program": {"added": 1, "updated": 0}}, before={"program": 1}, after={"program": 2})
        assert out["slug"] == "acme" and out["facts_before"] == 1 and out["facts_after"] == 2
        prog = next(c for c in out["concepts"] if c["concept"] == "program")
        assert prog["added"] == 1 and prog["before"] == 1 and prog["after"] == 2
        none = cov.view(row, stage="plan", report=None, entity=None, reasons=[], held=[], questions=0,
                        changes={}, before=None, after=None)
        assert none["facts_before"] is None and none["concepts"][0]["before"] is None

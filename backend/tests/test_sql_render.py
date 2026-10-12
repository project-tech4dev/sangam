"""How rows reach the model: compact, cited, and honest about what is missing."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.agent.tools.sql.render import (
    MAX_CELL_CHARS,
    MAX_OUTPUT_CHARS,
    MAX_SOURCES,
    NO_ROWS,
    render_caveats,
    render_cell,
    render_rows,
    render_sources,
)
from app.agent.tools.sql.validator import CitationPlan, ProvenancePlan

ORG = CitationPlan(output_column="id", kind="org")


class TestCells:
    def test_null_is_literal_so_the_model_can_reason_about_it(self):
        assert render_cell(None) == "NULL"

    def test_dates_are_iso(self):
        assert render_cell(date(2026, 9, 27)) == "2026-09-27"
        assert render_cell(datetime(2026, 9, 27, 14, 30, tzinfo=UTC)).startswith("2026-09-27T14:30")

    def test_decimals_do_not_render_as_decimal_repr(self):
        assert render_cell(Decimal("1500000.00")) == "1500000"

    def test_jsonb_is_compact(self):
        assert render_cell({"a": 1, "b": [2, 3]}) == '{"a":1,"b":[2,3]}'

    def test_long_cell_is_capped_and_says_how_long_it_really_was(self):
        rendered = render_cell("x" * 5000)
        assert len(rendered) < MAX_CELL_CHARS + 40
        assert "5000 chars total" in rendered


class TestRows:
    def test_markers_prefix_the_row_and_the_id_is_not_repeated(self):
        out = render_rows([{"id": 9, "name": "KABIL"}], citations=[ORG])
        assert out.splitlines()[0] == "columns: name"
        assert "[org:9] KABIL" in out
        assert "9 | KABIL" not in out, "the marker already carries the id"

    def test_no_rows_is_an_answer_not_a_failure(self):
        out = render_rows([])
        assert out == NO_ROWS
        assert "db_profile_column" in out, "the likely cause is a wrong filter value"

    def test_uncited_result_says_how_to_make_it_citable(self):
        out = render_rows([{"n": 4}])
        assert "no citation markers" in out.lower()
        assert "orgs.id" in out

    def test_limit_truncation_is_stated_in_the_strongest_terms(self):
        rows = [{"id": i, "name": f"o{i}"} for i in range(50)]
        out = render_rows(rows, citations=[ORG], limit=50, truncated=True)
        assert "NOT a complete picture" in out
        assert "Do not present these figures as totals" in out

    def test_output_budget_stops_before_the_context_window_does(self):
        rows = [{"id": i, "blob": "x" * 180} for i in range(200)]
        out = render_rows(rows, citations=[ORG])
        assert len(out) <= MAX_OUTPUT_CHARS + 400
        assert "more row(s) not shown" in out

    def test_null_id_produces_no_marker_for_that_row(self):
        """A NULL id must not render [org:None]."""
        out = render_rows([{"id": None, "name": "x"}], citations=[ORG])
        assert "[org:None]" not in out
        assert "None" not in out.replace("no citation markers", "")

    def test_citation_plan_for_a_column_not_in_the_result_is_ignored(self):
        out = render_rows([{"name": "x"}], citations=[ORG])
        assert "[org:" not in out


def test_caveats_are_passed_through_verbatim():
    assert render_caveats(["org_id is NULL for all 118 rows."]).startswith("caveats: ")
    assert render_caveats([]) == ""


class TestSources:
    """Where the rows came from, reported once per distinct source rather than per row."""

    PROV = (
        ProvenancePlan(output_column="__prov__o__url", table="orgs", role="url"),
        ProvenancePlan(output_column="__prov__o__name", table="orgs", role="name"),
        ProvenancePlan(output_column="__prov__o__fetched", table="orgs", role="fetched"),
    )

    def _row(self, url, name="NGO Darpan", fetched=datetime(2026, 9, 12, 14, 30, tzinfo=UTC), **extra):
        return {
            "id": extra.pop("id", 9),
            "__prov__o__url": url,
            "__prov__o__name": name,
            "__prov__o__fetched": fetched,
            **extra,
        }

    def test_the_line_grammar_is_a_contract(self):
        """frontend/features/ask/lib/sources.ts parses this. Changing it is a frontend change."""
        out = render_sources([self._row("https://x.test/a")], provenance=self.PROV)
        assert out == "sources: 1\n  orgs · https://x.test/a · NGO Darpan · 2026-09-12"

    def test_one_source_shared_by_many_rows_is_named_once(self):
        rows = [self._row("https://x.test/a", id=i) for i in range(20)]
        out = render_sources(rows, provenance=self.PROV)
        assert out.count("https://x.test/a") == 1

    def test_distinct_sources_are_capped(self):
        rows = [self._row(f"https://x.test/{i}", id=i) for i in range(30)]
        out = render_sources(rows, provenance=self.PROV)
        assert len(out.splitlines()) == MAX_SOURCES + 1
        assert f"of {MAX_SOURCES}+ shown" in out

    def test_a_long_url_is_never_truncated(self):
        """render_cell would cut it at 200 chars, and a truncated link is a dead link."""
        url = "https://x.test/" + "a" * 400
        out = render_sources([self._row(url)], provenance=self.PROV)
        assert url in out
        assert "chars total" not in out

    def test_a_row_with_no_recorded_url_is_skipped_not_rendered_blank(self):
        rows = [self._row("https://x.test/a"), self._row(None, name=None, fetched=None, id=1)]
        out = render_sources(rows, provenance=self.PROV)
        assert out == "sources: 1\n  orgs · https://x.test/a · NGO Darpan · 2026-09-12"

    def test_no_source_anywhere_says_so_rather_than_nothing(self):
        rows = [self._row(None, name=None, fetched=None)]
        assert "none recorded" in render_sources(rows, provenance=self.PROV)

    def test_a_skipped_shape_reports_its_reason(self):
        out = render_sources([{"n": 4}], provenance=[], skipped="the rows are aggregated")
        assert out == "sources: none — the rows are aggregated"

    def test_source_columns_leave_the_row_body(self):
        """The URL belongs in the sources block, not repeated on every row of the grid."""
        out = render_rows([self._row("https://x.test/a")], citations=[ORG], provenance=self.PROV)
        assert "https://x.test/a" not in out
        assert "[org:9]" in out

    def test_sources_cost_the_rows_nothing(self):
        """The block is budgeted separately, so provenance never pushes data out of the result."""
        rows = [{"id": i, "blob": "x" * 180} for i in range(200)]
        plain = render_rows(rows, citations=[ORG])
        withprov = render_rows(
            [{**r, "__prov__o__url": "https://x.test/a"} for r in rows],
            citations=[ORG],
            provenance=(self.PROV[0],),
        )
        assert withprov == plain

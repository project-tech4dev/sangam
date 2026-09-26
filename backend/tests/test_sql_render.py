"""How rows reach the model: compact, cited, and honest about what is missing."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.agent.tools.sql.render import (
    MAX_CELL_CHARS,
    MAX_OUTPUT_CHARS,
    NO_ROWS,
    render_caveats,
    render_cell,
    render_rows,
)
from app.agent.tools.sql.validator import CitationPlan

ORG = CitationPlan(output_column="id", kind="org")


class TestCells:
    def test_null_is_literal_so_the_model_can_reason_about_it(self):
        assert render_cell(None) == "NULL"

    def test_dates_are_iso(self):
        assert render_cell(date(2026, 9, 27)) == "2026-09-27"
        assert render_cell(datetime(2026, 9, 27, 14, 30)).startswith("2026-09-27T14:30")

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
        """news_mentions.org_id is NULL on every row — it must not render [org:None]."""
        out = render_rows([{"id": None, "name": "x"}], citations=[ORG])
        assert "[org:None]" not in out
        assert "None" not in out.replace("no citation markers", "")

    def test_citation_plan_for_a_column_not_in_the_result_is_ignored(self):
        out = render_rows([{"name": "x"}], citations=[ORG])
        assert "[org:" not in out


def test_caveats_are_passed_through_verbatim():
    assert render_caveats(["org_id is NULL for all 118 rows."]).startswith("caveats: ")
    assert render_caveats([]) == ""

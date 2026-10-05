"""The system prompt's contract with the tools."""

from __future__ import annotations

import re
from pathlib import Path

from app.agent.prompt import SYSTEM_PROMPT

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "agent" / "tools"

# Markers written as literal f-strings, e.g. f"[graph:{edge.uuid[:8]}]".
_LITERAL = re.compile(r"\[([a-z_]+):\{")


def emitted_markers() -> set[str]:
    """Every citation kind a tool can put in front of a row."""
    from app.agent.tools.sql.catalog import CITE_COLUMNS

    literal = {
        kind
        for path in TOOLS_DIR.glob("*.py")
        for kind in _LITERAL.findall(path.read_text(encoding="utf-8"))
    }
    return literal | set(CITE_COLUMNS.values())


def test_tools_emit_the_markers_we_think_they_do():
    """Guards the guard: if either source stops producing kinds, the test below
    passes vacuously."""
    assert emitted_markers() == {"org", "funder", "grant", "score", "graph"}


def test_prompt_documents_every_marker_the_tools_emit():
    missing = [kind for kind in sorted(emitted_markers()) if f"[{kind}:" not in SYSTEM_PROMPT]
    assert not missing, (
        f"tools emit {missing} but app/agent/instructions.md never names "
        f"{'them' if len(missing) > 1 else 'it'} — the model will not repeat "
        f"markers it was not told about, so those rows become uncitable"
    )


def test_prompt_is_loaded_not_empty():
    """A missing or truncated instructions.md would leave the agent answering from
    general knowledge with no citations — the exact failure the prompt prevents."""
    assert len(SYSTEM_PROMPT.strip()) > 500
    assert "Sangam" in SYSTEM_PROMPT


def test_prompt_names_every_registered_tool():
    """Routing rules reference tools by their exact Python identifier, so a renamed or newly added tool
    leaves the prompt pointing at nothing — or"""
    from app.agent.build import TOOLS

    missing = [t.name for t in TOOLS if t.name not in SYSTEM_PROMPT]
    assert not missing, f"registered but never mentioned in instructions.md: {missing}"


def test_retry_budget_in_the_prompt_matches_the_middleware():
    """The prompt asks the model to stop after N attempts and the middleware enforces N. If they drift,
    the model either gives up early or is cut off"""
    from app.agent.middleware import MAX_SQL_ATTEMPTS

    assert f"After {MAX_SQL_ATTEMPTS} failed attempts" in SYSTEM_PROMPT


class TestFunderShortlistProcedure:
    """Flow 2: one counted query, and an unknown funder never reads as a poor match."""

    def test_unrankable_funders_are_a_named_block(self):
        assert "not enough recorded to rank" in SYSTEM_PROMPT

    def test_each_criterion_has_three_states(self):
        for state in ("match", "no overlap", "not recorded"):
            assert state in SYSTEM_PROMPT

    def test_counts_travel_with_their_denominators(self):
        assert "criteria_known" in SYSTEM_PROMPT and "criteria_met" in SYSTEM_PROMPT

    def test_thematic_join_goes_through_the_crosswalk(self):
        assert "maps_to" in SYSTEM_PROMPT

    def test_the_assessment_is_offered_not_run(self):
        assert "do not run it unasked" in SYSTEM_PROMPT.lower()


class TestFunderAssessmentProcedure:
    """Flow 1: the rubric is read from the database, and what could not be scored is half the answer."""

    def test_weights_come_from_the_rubric_table(self):
        assert "rubric_criteria" in SYSTEM_PROMPT

    def test_total_is_out_of_available_points(self):
        assert "available points" in SYSTEM_PROMPT and "never out of 100" in SYSTEM_PROMPT

    def test_grant_size_is_named_unscorable(self):
        # funders.grant_size_min/max are not catalogued and never written, so 6a cannot be scored.
        assert "6a" in SYSTEM_PROMPT and "grant size" in SYSTEM_PROMPT.lower()

    def test_empty_eligibility_reads_as_unrecorded(self):
        assert "no eligibility bars recorded" in SYSTEM_PROMPT


class TestStoredAndComputedScoresStayApart:
    def test_rule_4_separates_a_stored_score_from_a_computed_one(self):
        rule_4 = SYSTEM_PROMPT.split("4. Be honest about scores.")[1].split("\n5. ")[0]
        assert "[score:" in rule_4 and "computed" in rule_4

    def test_rule_2_allows_an_uncited_total_only_when_labelled(self):
        rule_2 = SYSTEM_PROMPT.split("2. Cite everything.")[1].split("\n3. ")[0]
        assert "computed" in rule_2


def _rule(n: int) -> str:
    return SYSTEM_PROMPT.split(f"\n{n}. ")[1].split(f"\n{n + 1}. ")[0]


class TestShortlistGeographyAndLimits:
    """Review fixes: what the shortlist's columns must say about real rows."""

    def test_org_states_include_state_rows_not_just_district_parents(self):
        # Goonj has 7 state-level org_locations rows; a state's parent is India, a country.
        assert "kind = 'state'" in _rule(12)

    def test_a_region_is_known_never_met(self):
        # "Northeast India" has no child states in locations, so it cannot be expanded.
        assert "stated regional" in _rule(12)

    def test_a_cut_result_is_requeried_not_reported_short(self):
        assert "not shown" in _rule(12)

    def test_a_missing_maps_to_key_is_not_a_decided_null(self):
        # ->> reads NULL for both; only the JSON null is a decision.
        assert "'null'::jsonb" in _rule(12)


class TestAssessmentArithmetic:
    def test_available_points_come_from_sub_criteria_only(self):
        # rubric_criteria holds parent rows too; summing both double-counts M.
        assert "parent_id IS NOT NULL" in _rule(16)

    def test_a_stored_score_keeps_its_own_scale(self):
        assert "own scale" in _rule(19)

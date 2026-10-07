"""The system prompt's contract with the tools."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

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


class TestMatchingGoesThroughTheAssessor:
    """The supervisor narrows and reports; only the funder-assessor judges fit."""

    def test_fit_is_never_judged_in_db_query(self):
        assert "never judge fit yourself" in SYSTEM_PROMPT

    def test_unknowns_stay_not_recorded_never_ineligible(self):
        assert 'never "ineligible"' in SYSTEM_PROMPT

    def test_unverified_funders_are_a_named_block(self):
        assert "Unverified funders are named in their own block" in SYSTEM_PROMPT

    def test_the_verdict_is_repeated_never_computed(self):
        assert "never compute, adjust or round one" in SYSTEM_PROMPT
        assert "rank_key" in SYSTEM_PROMPT

    def test_the_procedure_is_the_skill(self):
        assert "funder-matching" in SYSTEM_PROMPT


class TestTheWaveSizeIsTheSetting:
    """A number frozen in prose would make MAX_PARALLEL_RESEARCH decorative."""

    def test_the_shipped_prompt_has_no_placeholder_left(self):
        assert "{{" not in SYSTEM_PROMPT

    def test_the_prompt_renders_from_the_settings_it_is_given(self):
        from app.agent.prompt import render_prompt
        from app.core.config import Settings

        assert "at most 3 funder-assessor" in render_prompt(Settings(max_parallel_research=3))


class TestStoredAndComputedScoresStayApart:
    def test_rule_4_separates_a_stored_score_from_a_computed_one(self):
        rule_4 = SYSTEM_PROMPT.split("4. Be honest about scores.")[1].split("\n5. ")[0]
        assert "[score:" in rule_4 and "computed" in rule_4

    def test_rule_2_allows_an_uncited_total_only_when_labelled(self):
        rule_2 = SYSTEM_PROMPT.split("2. Cite everything.")[1].split("\n3. ")[0]
        assert "computed" in rule_2


def _matching_prompt(spec: str) -> str:
    from app.agent import build

    return getattr(build, spec)["system_prompt"]


@pytest.mark.parametrize("spec", ["READINESS", "ASSESSOR"])
class TestTheMatchingPromptsDefineTheChecks:
    """The prompts define each check; scoring.py turns checks into a verdict."""

    def test_it_is_loaded_and_names_its_tools(self, spec):
        from app.agent.build import ASSESSOR_TOOLS

        text = _matching_prompt(spec)
        assert len(text.strip()) > 500
        missing = [t.name for t in ASSESSOR_TOOLS if t.name not in text]
        assert not missing, f"{spec} prompt never names {missing}"

    def test_it_names_every_outcome_the_schema_accepts(self, spec):
        from typing import get_args

        from app.agent.assessment import Outcome

        for word in get_args(Outcome):
            assert f"`{word}`" in _matching_prompt(spec), word

    def test_it_names_no_verdict_or_weight(self, spec):
        # Weights live in scoring.py; a model told about a score starts returning one, which extra="forbid" rejects.
        from app.agent.scoring import WEIGHTS

        text = _matching_prompt(spec)
        assert not re.search(r"\b(score|gate|rank_key|tier)\b", text, re.IGNORECASE)
        for points, _ in WEIGHTS.values():
            assert f"{points} points" not in text

    def test_absence_is_never_a_fail(self, spec):
        assert "never `fail`" in _matching_prompt(spec)

    def test_it_lists_its_tables_so_no_describe_is_needed(self, spec):
        # Describing each table before querying it was most of the 50 queries per shortlist.
        text = _matching_prompt(spec)
        assert "### Tables" in text
        assert "db_describe_table only when a query fails" in text


class TestTheAssessorPromptJudgesOnlyTheFunderSide:
    def test_it_names_every_area_level_the_schema_accepts(self):
        from typing import get_args

        from app.agent.assessment import AreaLevel

        for word in get_args(AreaLevel):
            assert f"`{word}`" in _matching_prompt("ASSESSOR"), word

    def test_it_asks_for_the_funder_facts_the_scorer_reads(self):
        text = _matching_prompt("ASSESSOR")
        for field in ("funder_type", "section_135_bound", "foreign_funder", "shared_districts"):
            assert f"`{field}`" in text, field

    def test_programme_is_the_organisations_own_and_follows_theme(self):
        text = _matching_prompt("ASSESSOR")
        assert "programs where org_id is the organisation" in text
        assert "when `theme` is `fail` there is no shared theme" in text


class TestTheReadinessPromptJudgesOnlyTheOrganisation:
    def test_a_short_count_is_not_a_fail(self):
        # The A3 gate: 1 of 4 grants concluded failed projects_3 and capped 14 funders at weak.
        assert "A count below a bar is not evidence against it" in _matching_prompt("READINESS")

    def test_it_never_sees_the_funder(self):
        text = _matching_prompt("READINESS")
        assert "funder_footprints" not in text
        assert "funder_eligibility" not in text


def test_the_supervisor_prompt_names_both_matching_subagents():
    assert "funder-assessor" in SYSTEM_PROMPT
    assert "org-readiness" in SYSTEM_PROMPT

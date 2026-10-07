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


class TestMatchingGoesThroughTheAssessor:
    """The supervisor narrows and reports; only the funder-assessor judges fit."""

    def test_fit_is_never_judged_in_db_query(self):
        assert "never judge fit yourself" in SYSTEM_PROMPT

    def test_unknowns_stay_not_recorded_never_ineligible(self):
        assert 'never "ineligible"' in SYSTEM_PROMPT

    def test_unrankable_funders_are_a_named_block(self):
        assert "not enough recorded" in SYSTEM_PROMPT

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


class TestTheAssessorPromptIsTheCriteria:
    """The checklist is the criteria: editing it is how a rule changes."""

    def test_it_is_loaded_and_names_its_tools(self):
        from app.agent.build import ASSESSOR, ASSESSOR_TOOLS

        text = ASSESSOR["system_prompt"]
        assert len(text.strip()) > 500
        missing = [t.name for t in ASSESSOR_TOOLS if t.name not in text]
        assert not missing, f"funder_assessor.md never names {missing}"

    def test_it_names_every_tier_and_outcome_the_schema_accepts(self):
        from app.agent.build import ASSESSOR

        text = ASSESSOR["system_prompt"]
        for word in ("strong", "possible", "weak", "not_enough_recorded", "met", "fail", "unknown"):
            assert f"`{word}`" in text, word

    def test_absence_is_never_a_fail(self):
        from app.agent.build import ASSESSOR

        assert "never `fail`" in ASSESSOR["system_prompt"]

    def test_only_an_eligibility_fail_makes_a_shared_theme_weak(self):
        # area fail + theme met is possible; "any check is fail" also made it weak.
        from app.agent.build import ASSESSOR

        weak = next(line for line in ASSESSOR["system_prompt"].splitlines() if line.startswith("| `weak`"))
        assert "any eligibility check is `fail`" in weak

    def test_a_short_count_is_not_a_fail(self):
        # The A3 gate: 1 of 4 grants concluded failed projects_3 and capped 14 funders at weak.
        from app.agent.build import ASSESSOR

        assert "A count below a bar is not evidence against it" in ASSESSOR["system_prompt"]

    def test_the_supervisor_prompt_names_the_assessor(self):
        assert "funder-assessor" in SYSTEM_PROMPT

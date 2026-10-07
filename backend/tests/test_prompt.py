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


class TestMatchingGoesThroughCompareFit:
    """The supervisor resolves and reports; only compare_fit judges fit."""

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

    def test_it_is_called_once_and_never_rechecked(self):
        assert "Call compare_fit once per question" in SYSTEM_PROMPT
        assert "never re-check what compare_fit returned" in SYSTEM_PROMPT


def test_the_shipped_prompt_has_no_placeholder_left():
    assert "{{" not in SYSTEM_PROMPT


class TestStoredAndComputedScoresStayApart:
    def test_rule_4_separates_a_stored_score_from_a_computed_one(self):
        rule_4 = SYSTEM_PROMPT.split("4. Be honest about scores.")[1].split("\n5. ")[0]
        assert "[score:" in rule_4 and "computed" in rule_4

    def test_rule_2_allows_an_uncited_total_only_when_labelled(self):
        rule_2 = SYSTEM_PROMPT.split("2. Cite everything.")[1].split("\n3. ")[0]
        assert "computed" in rule_2

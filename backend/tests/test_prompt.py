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


class TestRouting:
    """Judgements and profiles go to the matching tools; SQL keeps every other fact (M3)."""

    MATCHING = ("match_funders", "explain_match", "get_org", "get_funder", "find_funders")

    def test_rule_11_names_every_matching_tool_and_db_query(self):
        assert all(t in _rule(11) for t in (*self.MATCHING, "db_query"))

    def test_a_judgement_is_never_rebuilt_in_sql(self):
        assert "Never re-derive a judgement" in _rule(12)

    def test_an_ambiguous_name_is_asked_about(self):
        assert "ask the user which one" in _rule(13) and "Never pick" in _rule(13)

    def test_unrankable_funders_are_a_named_block_and_the_version_is_stated(self):
        assert "not enough recorded to rank" in _rule(14) and "criteria version" in _rule(14)

    def test_only_a_marked_fail_is_a_failure(self):
        assert "Only a check the tool marks fail" in _rule(14)

    def test_empty_eligibility_reads_as_unrecorded(self):
        assert "no eligibility bars recorded" in _rule(15)

    def test_sql_no_longer_claims_every_data_question(self):
        assert "Every data question is answered by writing SQL" not in SYSTEM_PROMPT
        assert "compare, rank" not in SYSTEM_PROMPT


class TestStoredAndComputedScoresStayApart:
    def test_rule_4_separates_a_stored_score_from_a_computed_one(self):
        rule_4 = SYSTEM_PROMPT.split("4. Be honest about scores.")[1].split("\n5. ")[0]
        assert "[score:" in rule_4 and "computed" in rule_4

    def test_rule_2_allows_an_uncited_total_only_when_labelled(self):
        rule_2 = SYSTEM_PROMPT.split("2. Cite everything.")[1].split("\n3. ")[0]
        assert "computed" in rule_2


def _rule(n: int) -> str:
    return SYSTEM_PROMPT.split(f"\n{n}. ")[1].split(f"\n{n + 1}. ")[0]

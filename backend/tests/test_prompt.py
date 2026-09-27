"""The system prompt's contract with the tools.

CLAUDE.md: "Every database and graph row carries a citation marker ... because
app/agent/prompt.py requires the model to repeat it inline next to each fact. A
tool that returns uncited rows produces uncitable answers."

That contract is only kept if the prompt actually names every marker the tools
emit, so these tests derive the marker set from the tool sources rather than
hardcoding it — adding a tool that emits a new marker fails here, which is the
point.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.agent.prompt import SYSTEM_PROMPT

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "agent" / "tools"

# Markers written as literal f-strings, e.g. f"[graph:{edge.uuid[:8]}]".
_LITERAL = re.compile(r"\[([a-z_]+):\{")


def emitted_markers() -> set[str]:
    """Every citation kind a tool can put in front of a row.

    Two sources, because the tools produce them two ways. graph_tools writes its
    marker as a literal f-string. db_query derives its markers from the catalog
    at runtime, so there is no literal to scan for — CITE_COLUMNS is the
    authoritative list, and scanning alone would silently report none.
    """
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
    """Routing rules reference tools by their exact Python identifier, so a
    renamed or newly added tool leaves the prompt pointing at nothing — or
    silently never being used."""
    from app.agent.build import TOOLS

    missing = [t.name for t in TOOLS if t.name not in SYSTEM_PROMPT]
    assert not missing, f"registered but never mentioned in instructions.md: {missing}"


def test_retry_budget_in_the_prompt_matches_the_middleware():
    """The prompt asks the model to stop after N attempts and the middleware
    enforces N. If they drift, the model either gives up early or is cut off
    mid-explanation."""
    from app.agent.middleware import MAX_SQL_ATTEMPTS

    assert f"After {MAX_SQL_ATTEMPTS} failed attempts" in SYSTEM_PROMPT

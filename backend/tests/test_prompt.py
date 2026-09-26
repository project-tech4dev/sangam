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

# Markers are emitted from f-strings, e.g. f"[org:{r['id']}] {r['name']}".
_EMITTED = re.compile(r"\[([a-z_]+):\{")


def emitted_markers() -> set[str]:
    return {
        kind
        for path in TOOLS_DIR.glob("*.py")
        for kind in _EMITTED.findall(path.read_text(encoding="utf-8"))
    }


def test_tools_emit_the_markers_we_think_they_do():
    """Guards the guard: if the regex stops matching, the test below passes vacuously."""
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


def test_prompt_names_each_registered_tool_it_routes_to():
    """Routing rules reference tools by their exact Python identifier; a renamed
    tool leaves the prompt pointing at something that no longer exists."""
    from app.agent import build  # noqa: F401  — import check only

    for tool_name in ("get_grants", "search_graph"):
        assert tool_name in SYSTEM_PROMPT

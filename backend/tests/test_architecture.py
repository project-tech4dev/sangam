"""Code-boundary rules from CLAUDE.md, checked over the source with ast so they cannot drift into prose."""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
APP = BACKEND / "app"
# Code outside app/ that may be the only caller of an app/ name. Tests are not callers.
CALLERS = [APP, REPO / "seed", REPO / "scripts"]


def _top_level_names(path: Path) -> list[tuple[str, int]]:
    """Functions and classes defined at module level; a decorated one is registered by its decorator."""
    names = []
    for node in ast.parse(path.read_text()).body:
        defines = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if defines and not node.decorator_list and node.name != "main" and not node.name.startswith("__"):
            names.append((node.name, node.lineno))
    return names


def test_r6_every_top_level_name_has_a_caller():
    # By name across files, so a dead copy that shares a live one's name (`_money` x3) is not caught.
    text = "\n".join(p.read_text() for root in CALLERS for p in root.rglob("*.py"))
    counts: dict[str, int] = {}
    for word in re.findall(r"\b\w+\b", text):
        counts[word] = counts.get(word, 0) + 1
    dead = sorted(
        f"{path.relative_to(BACKEND)}:{line} {name}"
        for path in APP.rglob("*.py")
        for name, line in _top_level_names(path)
        if counts.get(name, 0) < 2
    )
    assert not dead, "defined but never used outside tests (R6 in CLAUDE.md); delete it:\n" + "\n".join(dead)

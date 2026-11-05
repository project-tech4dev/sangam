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

# R1: the modules that build an agent, and so may import its tools.
BUILDERS = {"app/agent/build.py", "app/ingest/agent.py", "app/proposals/agent.py", "app/ingest/news/verify.py"}
# Ask's SQL engine and the catalog every agent reads live under agent/tools/sql/ but are not tools.
NOT_TOOLS = "app.agent.tools.sql"

# R2: where an import inside a function is the point, to keep a cold start or a cron job light.
COLD_START = ("app/api/routes/", "app/core/lifespan.py", "app/db/migrate.py", "app/integrations/", "app/ingest/news/",
              "app/ingest/calls/")
# The circular imports left. A later PR may shrink this set, never grow it.
CYCLES = {
    ("app/ingest/research_records.py", "app.ingest.source_guards"),  # phase 3
    ("app/ingest/research_records.py", "app.ingest.expectations"),  # phase 3
    ("app/ingest/source_guards.py", "app.ingest.research_records"),  # phase 3
    ("app/proposals/tools/reading_tools.py", "app.proposals.readers"),  # the subagent built from this module's tools
}


def _rel(path: Path) -> str:
    return str(path.relative_to(BACKEND))


def _imports(tree: ast.AST) -> list[tuple[ast.AST, str]]:
    """Each app import as (node, target), a `from pkg import mod` resolving to `pkg.mod`."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node, a.name) for a in node.names if a.name.startswith("app.")]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
            out += [(node, f"{node.module}.{a.name}") for a in node.names]
    return out


def _inside_functions(tree: ast.AST) -> set[int]:
    return {id(n) for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            for n in ast.walk(f) if isinstance(n, (ast.Import, ast.ImportFrom))}


def _module_of(target: str) -> str:
    """`app.ingest.vault.read` -> `app.ingest.vault`, the longest prefix that is a module or package."""
    parts = target.split(".")
    for end in range(len(parts), 1, -1):
        base = BACKEND.joinpath(*parts[:end])
        if base.with_suffix(".py").exists() or (base / "__init__.py").exists():
            return ".".join(parts[:end])
    return target


def test_r1_only_a_builder_imports_from_tools():
    wrong = sorted(
        f"{_rel(path)}:{node.lineno} {target}"
        for path in APP.rglob("*.py")
        if "/tools/" not in _rel(path) and _rel(path) not in BUILDERS
        for node, target in _imports(ast.parse(path.read_text()))
        if ".tools." in f"{target}." and not target.startswith(NOT_TOOLS)
    )
    assert not wrong, "only an agent's builder imports from tools/ (R1); move the helper out:\n" + "\n".join(wrong)


def test_r2_an_import_inside_a_function_has_a_reason():
    wrong = []
    for path in APP.rglob("*.py"):
        if _rel(path).startswith(COLD_START):
            continue
        tree = ast.parse(path.read_text())
        inner = _inside_functions(tree)
        wrong += [f"{_rel(path)}:{node.lineno} {_module_of(target)}" for node, target in _imports(tree)
                  if id(node) in inner and (_rel(path), _module_of(target)) not in CYCLES]
    assert not wrong, "move these imports to the top of the module (R2); a cycle is fixed, not hidden:\n" + \
        "\n".join(sorted(wrong))


def test_r2_every_listed_cycle_is_still_there():
    found = set()
    for rel, _ in CYCLES:
        tree = ast.parse((BACKEND / rel).read_text())
        inner = _inside_functions(tree)
        found |= {(rel, _module_of(t)) for node, t in _imports(tree) if id(node) in inner}
    assert CYCLES <= found, f"no longer lazy, so take it off CYCLES: {sorted(CYCLES - found)}"


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

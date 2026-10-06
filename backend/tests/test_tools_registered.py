"""Ask Sangam's tool package: every tool is registered, and the matching tools hold no SQL (R23)."""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

from app.agent import tools
from app.agent.build import TOOLS

TOOLS_DIR = Path(tools.__file__).parent
# files.py predates the matching work and Ask Sangam has never registered it; Import reuses its helpers.
UNREGISTERED = {"download_file", "read_pdf"}


def test_every_tool_defined_is_also_registered():
    defined = {
        obj.name
        for info in pkgutil.iter_modules(tools.__path__)
        for _, obj in inspect.getmembers(importlib.import_module(f"{tools.__name__}.{info.name}"))
        if isinstance(obj, BaseTool)
    }
    assert defined - {t.name for t in TOOLS} - UNREGISTERED == set()


@pytest.mark.parametrize("module", ["match_tools.py", "profile_tools.py", "match_render.py"])
def test_matching_tool_modules_hold_no_sql_and_no_engine_internals(module):
    src = (TOOLS_DIR / module).read_text(encoding="utf-8")
    assert not re.search(r"\bSELECT\b|\bFROM\b|execute\(", src), "SQL belongs in app/matching/evidence.py"
    imported = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) and n.module}
    banned = {"app.matching.evidence", "app.matching.engine", "app.matching.registry"}
    if module == "match_render.py":
        banned -= {"app.matching.evidence"}  # it renders OrgProfile, the bundle's type
    assert not imported & banned

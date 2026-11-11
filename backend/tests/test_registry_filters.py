"""The Registry's North East, which the SQL filter and the browser's rows.ts must list alike."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.repositories.registry import NORTH_EAST


def test_north_east_matches_the_frontend_list():
    rows_ts = Path(__file__).resolve().parents[2] / "frontend/features/registry/rows.ts"
    if not rows_ts.exists():
        pytest.skip("frontend not checked out")
    block = re.search(r"NORTH_EAST = \[(.*?)\]", rows_ts.read_text(), re.DOTALL)
    assert tuple(re.findall(r'"([^"]+)"', block.group(1))) == NORTH_EAST

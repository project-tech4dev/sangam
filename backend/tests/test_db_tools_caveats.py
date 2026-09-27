"""Curated tools must carry the same data caveats as the SQL tools.

The catalog records what is wrong with the DATA, and db_query injects it into
every result. search_orgs reads the same broken rows through the same
locations.parent_id rollup, so without this it returned them uncaveated and the
model fell back on its own geography knowledge — which caught Dimapur and
Tamenglong and missed Bishnupur. Catching most is worse than catching none,
because the misses read as confirmations.
"""

from __future__ import annotations

import pytest

from app.agent.tools import db_tools
from app.agent.tools.sql.catalog import DEFECTS

ROWS = [
    {
        "id": 5, "name": "PRDA", "slug": "prda", "legal_form": "Society",
        "registration_date": None, "source_name": "darpan-portal", "source_url": None,
        "fetched_at": None, "district": "BISHNUPUR", "state": "Assam",
        "sectors": [], "ids": "",
    }
]


class _Cursor:
    def __init__(self, rows): self._rows = rows
    async def fetchall(self): return self._rows


class _Conn:
    def __init__(self, rows): self._rows = rows
    async def execute(self, sql, params=None, **kw): return _Cursor(self._rows)


class _PoolCtx:
    def __init__(self, rows): self._rows = rows
    async def __aenter__(self): return _Conn(self._rows)
    async def __aexit__(self, *a): return False


class _Pool:
    def __init__(self, rows): self._rows = rows
    def connection(self): return _PoolCtx(self._rows)


@pytest.fixture
def fake_pool(monkeypatch):
    def install(rows):
        monkeypatch.setattr(db_tools, "get_pool", lambda: _Pool(rows))
    return install


async def test_search_orgs_carries_the_locations_caveat(fake_pool):
    fake_pool(ROWS)
    out = await db_tools.search_orgs.ainvoke({"query": "Assam"})
    assert "CAVEAT" in out
    for district in ("DIMAPUR", "BISHNUPUR", "TAMENGLONG"):
        assert district in out, f"{district} must be named; the model misses the ones it is not told"


async def test_caveat_appears_even_when_nothing_matched(fake_pool):
    """'No organisations in Assam' is as wrong as a bad list if the rollup is broken."""
    fake_pool([])
    out = await db_tools.search_orgs.ainvoke({"query": "Assam"})
    assert "CAVEAT" in out


async def test_the_caveat_text_comes_from_the_catalog(fake_pool):
    """One source of truth: fixing the data means deleting the catalog line, not
    hunting for duplicated prose in the curated tools."""
    fake_pool(ROWS)
    out = await db_tools.search_orgs.ainvoke({"query": "Assam"})
    assert DEFECTS["locations"][0] in out


def test_helper_is_silent_for_tables_with_no_known_defects():
    assert db_tools._caveats("rubrics") == ""
    assert db_tools._caveats() == ""

"""The SQL discovery tools, and db_query's edge cases, against a fake executor."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from app.agent.tools import sql_tools
from app.agent.tools.sql.catalog import CATALOG, DEFECTS
from app.agent.tools.sql.executor import PsycopgExecutor
from app.db.pool import caveats_given

REAL_EXECUTOR = sql_tools._executor


class FakeExecutor:
    rows: list[dict] = []
    error: Exception | None = None
    seen: list = []

    async def run(self, query):
        FakeExecutor.seen.append(query)
        if FakeExecutor.error is not None:
            raise FakeExecutor.error
        return FakeExecutor.rows


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    FakeExecutor.rows, FakeExecutor.error, FakeExecutor.seen = [], None, []
    monkeypatch.setattr(sql_tools, "_executor", FakeExecutor)
    token = caveats_given.set(None)
    yield
    caveats_given.reset(token)


async def query(sql: str) -> ToolMessage:
    call = {"name": "db_query", "args": {"sql": sql, "purpose": "t"}, "id": "c1", "type": "tool_call"}
    return await sql_tools.db_query.ainvoke(call)


def test_the_executor_takes_the_timeout_from_settings(monkeypatch):
    monkeypatch.setattr(sql_tools, "get_settings", lambda: SimpleNamespace(sql_timeout_ms=1234))
    ex = REAL_EXECUTOR()
    assert isinstance(ex, PsycopgExecutor) and ex._timeout_ms == 1234


async def test_list_tables_counts_the_catalog():
    out = await sql_tools.db_list_tables.ainvoke({})
    assert out.startswith(f"{len(CATALOG)} tables are readable:")
    assert "db_profile_column" in out


async def test_list_tables_error_is_a_string(monkeypatch):
    monkeypatch.setattr(sql_tools, "CATALOG", None)
    assert (await sql_tools.db_list_tables.ainvoke({})).startswith("db_list_tables failed:")


async def test_describe_needs_a_name():
    assert "at least one" in await sql_tools.db_describe_table.ainvoke({"tables": " , "})


async def test_describe_shows_columns_keys_both_directions_and_caveats():
    heavy = next(n for n, t in CATALOG.items() if any(c.heavy for c in t.columns))
    out = await sql_tools.db_describe_table.ainvoke({"tables": f"ORGS, nope, {heavy}"})
    assert "orgs — " in out and "primary key: id" in out
    assert "orgs.registered_location_id -> locations.id" in out
    assert "referenced by" in out
    assert "nope: unknown table" in out
    assert "large; omitted from SELECT *" in out
    if DEFECTS.get("orgs"):
        assert "CAVEAT:" in out


async def test_describe_lists_allowed_values():
    name = next(n for n, t in CATALOG.items() if any(c.values for c in t.columns))
    assert "one of:" in await sql_tools.db_describe_table.ainvoke({"tables": name})


async def test_describe_error_is_a_string(monkeypatch):
    monkeypatch.setattr(sql_tools, "CATALOG", {"orgs": None})
    out = await sql_tools.db_describe_table.ainvoke({"tables": "orgs"})
    assert out.startswith("db_describe_table failed:")


async def test_profile_refuses_an_unknown_table_or_column():
    out = await sql_tools.db_profile_column.ainvoke({"table": "secrets", "column": "x"})
    assert "unknown table 'secrets'" in out
    out = await sql_tools.db_profile_column.ainvoke({"table": "orgs", "column": "password"})
    assert "no readable column 'password'" in out and "Columns of orgs:" in out


async def test_profile_with_no_rows_does_not_say_empty():
    out = await sql_tools.db_profile_column.ainvoke({"table": "orgs", "column": "legal_form"})
    assert "Do not report it as empty" in out
    assert "GROUP BY" in FakeExecutor.seen[0].sql.upper()


async def test_profile_lists_values_with_counts_and_caveats():
    FakeExecutor.rows = [{"value": "Public Charitable Trust", "n": 7}, {"value": None, "n": 2}]
    out = await sql_tools.db_profile_column.ainvoke({"table": " Orgs ", "column": "LEGAL_FORM"})
    assert out.startswith("orgs.legal_form — 2 most common value(s)")
    assert "Public Charitable Trust  (7)" in out
    if DEFECTS.get("orgs"):
        assert DEFECTS["orgs"][0][:30] in out


async def test_profile_failure_is_a_string():
    FakeExecutor.error = RuntimeError("boom")
    out = await sql_tools.db_profile_column.ainvoke({"table": "orgs", "column": "legal_form"})
    assert out.startswith(sql_tools.PROFILE_FAILED_PREFIX) and "boom" in out


async def test_a_query_that_cannot_be_checked_is_rejected(monkeypatch):
    def broken(*a, **k):
        raise ValueError("parser blew up")

    monkeypatch.setattr(sql_tools, "validate", broken)
    message = await query("SELECT 1")
    assert "could not be checked (parser blew up)" in message.content and message.artifact is None


async def test_a_database_error_is_explained_with_the_sql_as_artifact():
    FakeExecutor.error = RuntimeError("connection reset")
    message = await query("SELECT id FROM orgs")
    assert message.artifact["sql"].startswith("SELECT")
    assert message.content


async def test_no_rows_says_none_here_is_not_none_exist():
    message = await query("SELECT id, name FROM orgs")
    assert "0 row(s)" in message.content and "not 'none exist'" in message.content


async def test_rows_past_the_limit_are_cut_and_rewrites_reported():
    FakeExecutor.rows = [{"name": f"o{i}", "id": i} for i in range(200)]
    message = await query("SELECT name FROM orgs")
    assert "adjusted:" in message.content
    assert "row(s). tables: orgs." in message.content

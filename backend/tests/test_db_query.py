"""db_query's reply: the SQL that ran goes in the artifact, and a table's caveats come in full once a turn."""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage

from app.agent.tools import sql_tools
from app.agent.tools.sql.catalog import DEFECTS
from app.db.pool import caveats_given

TABLE = next(iter(sorted(DEFECTS)))


class FakeExecutor:
    async def run(self, query):
        return [{"id": 1}]


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    monkeypatch.setattr(sql_tools, "_executor", FakeExecutor)
    token = caveats_given.set(None)
    yield
    caveats_given.reset(token)


async def query(sql: str = f"SELECT id FROM {TABLE}") -> ToolMessage:
    call = {"name": "db_query", "args": {"sql": sql, "purpose": "test"}, "id": "c1", "type": "tool_call"}
    return await sql_tools.db_query.ainvoke(call)


async def test_the_sql_that_ran_is_the_artifact_not_the_text():
    message = await query()
    assert "executed:" not in message.content
    assert message.artifact["sql"].startswith("SELECT")


async def test_a_rejected_query_has_no_artifact():
    message = await query("DELETE FROM orgs")
    assert message.content.startswith("db_query rejected:") and message.artifact is None


async def test_caveats_are_given_in_full_once_a_turn():
    full = DEFECTS[TABLE][0][:40]
    caveats_given.set(set())
    first, second = (await query()).content, (await query()).content
    assert full in first
    assert full not in second and "as given earlier this turn" in second

    caveats_given.set(set())
    assert full in (await query()).content


async def test_without_a_turn_every_result_gives_them():
    for _ in range(2):
        assert DEFECTS[TABLE][0][:40] in (await query()).content

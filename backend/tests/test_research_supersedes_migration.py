"""0060: entity_research.supersedes, the fact keys a refresh removed."""

from __future__ import annotations

import pytest

from tests.test_source_snapshots_migration import conn  # noqa: F401 — the module's connection fixture

pytestmark = pytest.mark.integration


def test_supersedes_is_a_json_list_defaulting_to_empty(conn):  # noqa: F811
    row = conn.execute(
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_name = 'entity_research' AND column_name = 'supersedes'"
    ).fetchone()
    assert row["data_type"] == "jsonb" and row["is_nullable"] == "NO" and "'[]'" in row["column_default"]

"""The matching engine against the compose Postgres; every test rolls back."""

from __future__ import annotations

import copy

import psycopg
import pytest

from app.matching import registry
from app.matching.config import CriteriaError, load_yaml
from app.matching.themes import backfill_programme_themes

pytestmark = pytest.mark.integration


def raw_criteria(version=1, set_name="test-set"):
    raw = copy.deepcopy(load_yaml()[1])
    raw["set"], raw["version"] = set_name, version
    return raw


class TestRegistry:
    async def test_load_draft_records_hash_and_sha(self, db):
        v = await registry.load_draft(db, raw_criteria(), git_sha="abc123")
        rows = await registry.list_sets(db, "test-set")
        assert (v, rows[0]["status"], rows[0]["git_sha"]) == (1, "draft", "abc123")
        assert len(rows[0]["content_hash"]) == 64

    async def test_loading_the_same_content_twice_does_not_duplicate(self, db):
        await registry.load_draft(db, raw_criteria())
        await registry.load_draft(db, raw_criteria())
        assert len(await registry.list_sets(db, "test-set")) == 1

    async def test_same_version_different_content_is_refused(self, db):
        await registry.load_draft(db, raw_criteria())
        changed = raw_criteria()
        changed["checks"][0]["label"] = "something else"
        with pytest.raises(CriteriaError, match="bump"):
            await registry.load_draft(db, changed)

    async def test_no_active_version_raises(self, db):
        await registry.load_draft(db, raw_criteria())
        with pytest.raises(registry.NoActiveCriteria):
            await registry.get(db, "test-set")

    async def test_activate_retires_the_previous_and_rollback_reactivates(self, db):
        await registry.load_draft(db, raw_criteria(1))
        await registry.load_draft(db, raw_criteria(2))
        await registry.activate(db, "test-set", 1)
        await registry.activate(db, "test-set", 2)
        status = {r["version"]: r["status"] for r in await registry.list_sets(db, "test-set")}
        assert status == {1: "retired", 2: "active"}
        assert (await registry.get(db, "test-set")).version == 2
        await registry.activate(db, "test-set", 1)
        assert (await registry.get(db, "test-set")).version == 1

    async def test_a_specific_version_can_be_read_whatever_its_status(self, db):
        await registry.load_draft(db, raw_criteria(1))
        loaded = await registry.get(db, "test-set", 1)
        assert (loaded.version, loaded.status) == (1, "draft")

    async def test_the_index_allows_one_active_row(self, db):
        await registry.load_draft(db, raw_criteria(1))
        await registry.load_draft(db, raw_criteria(2))
        await db.execute("UPDATE criteria_sets SET status = 'active' WHERE set_name = 'test-set' AND version = 1")
        with pytest.raises(psycopg.errors.UniqueViolation):
            await db.execute("UPDATE criteria_sets SET status = 'active' WHERE set_name = 'test-set' AND version = 2")


class TestProgrammeThemes:
    async def test_tags_a_matching_programme_once(self, db):
        f = (await (await db.execute(
            "INSERT INTO funders (slug, name) VALUES ('t-funder', 'T Funder') RETURNING id")).fetchone())["id"]
        p = (await (await db.execute(
            "INSERT INTO programs (funder_id, name, description) VALUES (%s, 'Parivartan', "
            "'sustainable livelihoods for rural women artisans') RETURNING id", (f,))).fetchone())["id"]
        assert await backfill_programme_themes(db) >= 1
        tags = await (await db.execute(
            "SELECT t.slug, pt.is_inferred, pt.tagged_by FROM program_tags pt JOIN tags t ON t.id = pt.tag_id "
            "WHERE pt.program_id = %s", (p,))).fetchall()
        assert tags == [{"slug": "csr-education-and-livelihoods", "is_inferred": True,
                         "tagged_by": "taxonomy.clause_for"}]
        assert await backfill_programme_themes(db) == 0

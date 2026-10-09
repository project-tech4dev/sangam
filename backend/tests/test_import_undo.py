"""Staff undo an Import save and delete research: every catalog row a save wrote is logged, and undone exactly."""

from __future__ import annotations

import json

import pytest

from app.ingest import undo
from app.ingest.tools import catalog_tools
from app.repositories import ingest as repo
from tests.test_import_roles import running_as
from tests.test_storage import _PoolOf

pytestmark = pytest.mark.integration
SLUG = "zz-undo-test-foundation"


async def _staff(db):
    row = await (await db.execute("SELECT id FROM users WHERE is_staff LIMIT 1")).fetchone()
    if row is None:
        pytest.skip("no staff user seeded")
    from app.core.security import CallerScope

    return CallerScope(row["id"], True)


async def _research(db) -> int:
    finding = {"concept": "identity", "name": "Zz Undo Test Foundation", "funder_type": "csr_foundation",
               "website": "https://zz-undo.example.org", "source_url": "https://zz-undo.example.org/about",
               "evidence": "Zz Undo Test Foundation is the CSR arm of Zz Ltd.", "confidence": "high"}
    row = await (await db.execute(
        "INSERT INTO entity_research (entity_name, entity_kind, slug, status, summary, findings, fact_count, "
        "schema_version) VALUES ('Zz Undo Test Foundation', 'funder', %s, 'complete', 's', %s::jsonb, 1, 2) "
        "RETURNING id",
        (SLUG, json.dumps([finding])),
    )).fetchone()
    return row["id"]


async def _save(db, monkeypatch, staff) -> dict:
    monkeypatch.setattr(catalog_tools, "get_pool", lambda: _PoolOf(db))
    with running_as(staff):
        out = await catalog_tools.promote_research.ainvoke({"slug": SLUG})
    assert out.startswith("Promoted"), out
    return await (await db.execute(
        "SELECT * FROM promotions WHERE slug = %s ORDER BY id DESC LIMIT 1", (SLUG,))).fetchone()


async def _funders(db) -> int:
    row = await (await db.execute("SELECT count(*) AS n FROM funders WHERE slug = %s", (SLUG,))).fetchone()
    return row["n"]


async def test_a_save_is_logged_and_undone(db, monkeypatch):
    staff = await _staff(db)
    research_id = await _research(db)
    promo = await _save(db, monkeypatch, staff)
    assert promo["promoted_by"] == staff.user_id and promo["research_id"] == research_id
    writes = await (await db.execute(
        "SELECT table_name, action FROM catalog_writes WHERE promotion_id = %s", (promo["id"],))).fetchall()
    assert {"table_name": "funders", "action": "insert"} in writes
    assert await _funders(db) == 1

    listed = [r for r in await repo.list_research(_PoolOf(db), limit=200) if r["slug"] == SLUG]
    assert listed[0]["promotion_id"] == promo["id"] and listed[0]["saved_by"]

    assert await undo.delete_research(db, SLUG) is None  # a standing save is undone first
    done = await undo.undo(db, promo["id"], staff.user_id)
    assert done["removed"] == len(writes) and await _funders(db) == 0
    research = await (await db.execute(
        "SELECT saved, saved_at, resolved_funder_id FROM entity_research WHERE id = %s", (research_id,))).fetchone()
    assert research == {"saved": None, "saved_at": None, "resolved_funder_id": None}
    with pytest.raises(undo.UndoRefused):
        await undo.undo(db, promo["id"], staff.user_id)
    assert await undo.delete_research(db, SLUG) == 1


async def test_a_row_changed_since_refuses_the_whole_undo(db, monkeypatch):
    staff = await _staff(db)
    await _research(db)
    promo = await _save(db, monkeypatch, staff)
    await db.execute("UPDATE funders SET website = 'https://edited.example.org' WHERE slug = %s", (SLUG,))
    with pytest.raises(undo.UndoRefused, match="changed since"):
        await undo.undo(db, promo["id"], staff.user_id)
    assert await _funders(db) == 1


async def test_an_update_is_restored(db):
    staff = await _staff(db)
    funder = await (await db.execute("SELECT id, website FROM funders ORDER BY id LIMIT 1")).fetchone()
    if funder is None:
        pytest.skip("no funder seeded")
    promotion = await undo.start(db, None, "zz-update", staff.user_id)
    await db.execute("UPDATE funders SET website = 'https://from-research.example.org' WHERE id = %s", (funder["id"],))
    assert await undo.finish(db, promotion)
    done = await undo.undo(db, promotion, staff.user_id)
    after = await (await db.execute("SELECT website FROM funders WHERE id = %s", (funder["id"],))).fetchone()
    assert done["restored"] == 1 and after["website"] == funder["website"]


async def test_writes_outside_a_save_are_not_logged(db):
    before = await (await db.execute("SELECT count(*) AS n FROM catalog_writes")).fetchone()
    await db.execute("UPDATE funders SET website = website WHERE id = (SELECT min(id) FROM funders)")
    await db.execute("UPDATE funders SET website = 'https://x.example.org' WHERE id = (SELECT min(id) FROM funders)")
    after = await (await db.execute("SELECT count(*) AS n FROM catalog_writes")).fetchone()
    assert after["n"] == before["n"]


async def test_a_save_that_wrote_nothing_leaves_no_promotion(db):
    staff = await _staff(db)
    promotion = await undo.start(db, None, "zz-nothing", staff.user_id)
    assert not await undo.finish(db, promotion)
    gone = await (await db.execute("SELECT count(*) AS n FROM promotions WHERE id = %s", (promotion,))).fetchone()
    assert gone["n"] == 0

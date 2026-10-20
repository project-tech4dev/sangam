"""promote() branches that need storage faked or a private source: archived files shelved, staff rows held."""

from __future__ import annotations

import pytest

from app.ingest import promote as promote_mod
from app.ingest import staff_sources
from app.ingest.promote import link_partner_lines, promote
from tests.test_cov_promote import finding, funder, money, one, org, research, rows, tag

pytestmark = pytest.mark.integration
DIGEST = "a" * 64
DOC = {"source_type": "org_document", "evidence_tier": "evidenced"}


@pytest.fixture
def archive(monkeypatch):
    """A fake archive: every URL ending .pdf was archived; `taken` and `moves` steer _shelve."""
    state = {"taken": False, "move_ok": True, "moves": []}

    async def archived_key(bucket, url):
        return f"{DIGEST[:8]}/{DIGEST}-report.pdf" if url.endswith(".pdf") else None

    async def stat(bucket, key):
        return {"size": 1} if state["taken"] else None

    async def move(bucket, src, dst):
        state["moves"].append((src, dst))
        return state["move_ok"]

    monkeypatch.setattr(promote_mod.storage, "archived_key", archived_key)
    monkeypatch.setattr(promote_mod.storage, "stat", stat)
    monkeypatch.setattr(promote_mod.storage, "move", move)
    return state


async def test_an_archived_report_is_shelved_under_the_funders_slug(db, archive):
    name = f"Zz Shelf Ltd {tag()}"
    url = f"https://zz-shelf-{tag()}.example.org/annual.pdf"
    report = await promote(db, await research(db, name, [
        finding("identity", url, name=name),
        finding("document", url, title="Annual report", doc_type="annual_report", as_of="FY2023-24")]))
    slug = (await one(db, "SELECT slug FROM funders WHERE id = %s", report["entity"]["id"]))["slug"]
    doc = await one(db, "SELECT storage_path, content_hash FROM documents WHERE source_url = %s", url)
    assert doc["content_hash"] == DIGEST
    assert doc["storage_path"].startswith(f"source-archive/funders/{slug}/") and archive["moves"]


async def test_a_name_already_taken_gets_a_suffix_and_a_failed_move_keeps_the_old_key(db, archive):
    archive.update(taken=True, move_ok=False)
    name = f"Zz Shelf Two Ltd {tag()}"
    url = f"https://zz-shelf2-{tag()}.example.org/annual.pdf"
    await promote(db, await research(db, name, [finding("identity", url, name=name)]))
    (src, dst), = archive["moves"]
    assert dst.endswith(f"report-{DIGEST[:8]}.pdf")
    doc = await one(db, "SELECT storage_path, doc_type FROM documents WHERE source_url = %s", url)
    assert doc["storage_path"] == f"source-archive/{src}" and doc["doc_type"] == "other"


async def test_a_staff_figure_without_its_cell_marker_is_held(db, monkeypatch):
    async def none(bucket, url):
        return None
    monkeypatch.setattr(promote_mod.storage, "archived_key", none)
    url = staff_sources.source_url(f"book-{tag()}.xlsx")
    dataset = await one(db, "INSERT INTO documents (doc_type, source_url, title, is_public) "
                            "VALUES ('source_dataset', %s, 'Staff dataset', false) RETURNING id", url)
    name = f"Zz Staff Ltd {tag()}"
    report = await promote(db, await research(db, name, [
        finding("identity", "https://x.example.org", name=name),
        finding("csr_year", url, fiscal_year="FY2023-24", total_spent=money(1)),
        finding("document", url, title="Team workbook", doc_type="other"),
    ]))
    assert report["entity"]["status"] == "added"
    assert not await one(db, "SELECT 1 FROM funder_csr_years WHERE funder_id = %s", report["entity"]["id"])
    assert any("held" == v["state"] for v in report["facts"].values())
    assert dataset["id"] not in [r["id"] for r in await rows(
        db, "SELECT id FROM documents WHERE funder_id = %s", report["entity"]["id"])]


async def test_an_ngo_metric_from_a_stronger_source_takes_the_row(db, monkeypatch):
    async def none(bucket, url):
        return None
    monkeypatch.setattr(promote_mod.storage, "archived_key", none)
    name = f"Zz Metric Org {tag()}"
    oid = await org(db, name)
    await db.execute("INSERT INTO metrics (org_id, name, value, source_type, evidence, source_url) "
                     "VALUES (%s, 'Girls enrolled', 100, 'aggregator', 'claimed', 'https://agg.example.org')", (oid,))
    url = "https://zz-metric.example.org/report"
    await promote(db, await research(db, name, [
        finding("org_identity", url, name=name, **DOC),
        finding("metric", url, name="Girls enrolled", value=150, **DOC)], kind="org"))
    row = await one(db, "SELECT value, source_type, source_url FROM metrics WHERE org_id = %s", oid)
    assert (float(row["value"]), row["source_type"], row["source_url"]) == (150, "org_document", url)


async def test_link_partner_lines_matches_a_variant_and_ignores_a_missing_org(db):
    name = f"Zz Variant Trust {tag()}"
    oid = await org(db, name)
    fid = await funder(db, f"Zz Variant Giver {tag()}")
    line = await one(db, "INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name) "
                         "VALUES (%s, 'partner', 'FY2022-23', %s) RETURNING id", fid, f"{name} (ZVT)")
    assert await link_partner_lines(db, oid) == 1
    assert (await one(db, "SELECT partner_org_id FROM funder_activity WHERE id = %s", line["id"]))[
        "partner_org_id"] == oid
    assert await link_partner_lines(db, -1) == 0

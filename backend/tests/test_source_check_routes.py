"""The change check routes: staff only, and each refusal says why."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.api.routes import source_checks
from app.core.security import ANONYMOUS, CurrentUser, get_principal
from app.db.pool import get_pool
from app.ingest.refresh import service
from app.repositories import source_checks as repo
from tests.conftest import TEST_USER, make_app
from tests.cov_ingest_fakes import ScriptConn, ScriptPool

SLUG = "azim-premji-foundation"
RUN = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 11, 19, tzinfo=UTC)
RUN_ROW = {"run_id": RUN, "slug": SLUG, "depth": "free", "decision": "nothing to do", "started_at": NOW,
           "finished_at": NOW, "error": None, "refresh_row_id": None, "refresh_summary": None,
           "requested_by": "dev@sangam.local", "sources": 1}
CHECK_ROW = {"url": "https://a.org", "status": "differs", "detail": "1 paragraphs removed, 1 added",
             "findings_intact": 1, "findings_broken": 0, "findings_unanchored": 0, "judge": None,
             "removed_text": ["old"], "added_text": ["new"], "evidence": [{"verdict": "intact", "sentence": "s"}],
             "baseline_snapshot_id": 1, "new_snapshot_id": 10, "baseline_seen_at": NOW,
             "baseline_hash": "a" * 64, "today_hash": "b" * 64}


def client(principal: CurrentUser | None = None) -> httpx.AsyncClient:
    app = make_app(source_checks.router)
    app.dependency_overrides[get_pool] = lambda: ScriptPool()
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _value(v):
    return v


@pytest.mark.parametrize("who", [ANONYMOUS, CurrentUser(id=TEST_USER, is_staff=False)])
async def test_only_staff_may_check(who):
    async with client(who) as c:
        r = await c.post(f"/api/ingest/research/{SLUG}/checks", json={"depth": "free"})
    assert r.status_code in (401, 403)


async def test_the_baseline_lists_each_source(monkeypatch):
    src = service.Source("https://a.org", "page", 1, "2026-11-19", True, 79)
    monkeypatch.setattr(service, "baseline_view", lambda conn, slug: _value(([src], 0)))
    monkeypatch.setattr(repo, "entity_name", lambda conn, slug: _value("Azim Premji Foundation"))
    async with client() as c:
        r = await c.get(f"/api/ingest/research/{SLUG}/baseline")
    assert r.status_code == 200
    assert r.json() == {"slug": SLUG, "name": "Azim Premji Foundation", "unrecorded": 0, "sources": [
        {"url": "https://a.org", "kind": "page", "snapshot_id": 1, "read_on": "2026-11-19", "archived": True,
         "facts": 79}]}


async def test_a_free_check_returns_what_it_found(monkeypatch):
    asked = {}

    async def run(pool, slug, depth, refresh, user_id):
        asked.update(slug=slug, depth=depth, refresh=refresh)
        return RUN

    monkeypatch.setattr(service, "run", run)
    monkeypatch.setattr(repo, "get_run", lambda conn, run_id: _value({**RUN_ROW, "checks": [CHECK_ROW]}))
    async with client() as c:
        r = await c.post(f"/api/ingest/research/{SLUG}/checks", json={"depth": "free"})
    assert r.status_code == 200 and asked == {"slug": SLUG, "depth": "free", "refresh": False}
    body = r.json()
    assert body["decision"] == "nothing to do" and body["checks"][0]["added_text"] == ["new"]
    assert (body["checks"][0]["baseline_hash"], body["checks"][0]["today_hash"]) == ("a" * 64, "b" * 64)


async def test_an_update_needs_the_full_check():
    async with client() as c:
        r = await c.post(f"/api/ingest/research/{SLUG}/checks", json={"depth": "free", "refresh": True})
    assert r.status_code == 422


@pytest.mark.parametrize(("error", "says"), [(service.NoBaseline(SLUG), "Research it once first"),
                                             (service.Busy(SLUG), "already running")])
async def test_a_refused_check_says_why(monkeypatch, error, says):
    async def run(*a):
        raise error

    monkeypatch.setattr(service, "run", run)
    async with client() as c:
        r = await c.post(f"/api/ingest/research/{SLUG}/checks", json={"depth": "free"})
    assert r.status_code == 409 and says in r.json()["detail"]


async def test_history_and_one_run(monkeypatch):
    monkeypatch.setattr(repo, "list_runs", lambda conn, slug: _value([RUN_ROW]))
    monkeypatch.setattr(repo, "get_run", lambda conn, run_id: _value(None))
    async with client() as c:
        listed = await c.get(f"/api/ingest/research/{SLUG}/checks")
        missing = await c.get(f"/api/ingest/checks/{RUN}")
    assert [r["run_id"] for r in listed.json()] == [str(RUN)]
    assert missing.status_code == 404


async def test_tracked_lists_what_a_check_can_run_on(monkeypatch):
    row = {"slug": SLUG, "kind": "funder", "id": 12, "sources": 4, "last_checked": None}
    monkeypatch.setattr(repo, "list_tracked", lambda conn: _value([row]))
    async with client() as c:
        r = await c.get("/api/ingest/tracked")
    assert r.status_code == 200 and r.json() == [row]


async def test_an_update_that_cannot_be_saved_is_refused_before_anything_is_paid(monkeypatch):
    monkeypatch.setattr(service, "update_refused", lambda pool, slug: _value("already researched today"))
    monkeypatch.setattr(service, "run", lambda *a: pytest.fail("ran a paid check for an update that cannot save"))
    async with client() as c:
        r = await c.post(f"/api/ingest/research/{SLUG}/checks", json={"depth": "full", "refresh": True})
    assert r.status_code == 409 and r.json()["detail"] == "already researched today"


async def test_tracked_takes_kind_and_id_from_the_saved_row():
    # A later run that found nothing has kind 'unknown'; the saved row still names the funder.
    sql = repo.TRACKED_SQL
    assert "array_agg(r.entity_kind" not in sql
    assert "CASE WHEN x.resolved_funder_id IS NOT NULL THEN 'funder' ELSE 'org' END AS kind" in sql
    assert "coalesce(x.resolved_funder_id, x.resolved_org_id) AS id" in sql


async def test_tracked_is_staff_only():
    async with client(CurrentUser(id=TEST_USER, is_staff=False)) as c:
        r = await c.get("/api/ingest/tracked")
    assert r.status_code == 403


async def test_the_name_is_the_newest_researchs():
    conn = ScriptConn([("coalesce(canonical_name, entity_name)", {"name": "Pratham Education Foundation"})])
    assert await repo.entity_name(conn, SLUG) == "Pratham Education Foundation"
    assert "ORDER BY researched_on DESC" in conn.calls[0][0] and conn.calls[0][1] == (SLUG,)
    assert await repo.entity_name(ScriptConn(), SLUG) is None

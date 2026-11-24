"""The change check from the Scout screen: free stops before any model, every run is saved with its decision."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.ingest import brief
from app.ingest.refresh import (
    baseline,
    compare,
    decision,
    delta,
    discover,
    evidence,
    fetch_status,
    judge,
    save,
    service,
)
from tests.cov_ingest_fakes import ScriptConn, ScriptPool

SLUG = "azim-premji-foundation"
URL = "https://a.org/about"
USER = UUID("00000000-0000-0000-0000-000000000001")


def base(url: str = URL, **over) -> baseline.Baseline:
    return baseline.Baseline(**{"url": url, "snapshot_id": 7, "kind": "page", "text_hash": "a" * 64,
                                "archive_key": "k/about.md", "research_id": 31, "researched_on": date(2026, 11, 14),
                                **over})


def check(status: str, url: str = URL) -> compare.Check:
    return compare.Check(base(url), fetch_status.Today(url, fetch_status.OK, "HTTP 200"), status)


@pytest.mark.parametrize(("statuses", "redesign", "want"), [
    ((compare.UNCHANGED, compare.MINOR, fetch_status.UNVERIFIED), False, decision.NOTHING),
    ((compare.UNCHANGED, compare.DIFFERS), False, service.NEEDS_JUDGE),
    ((compare.DIFFERS, compare.CHANGED), False, decision.REFRESH),
    ((fetch_status.DEAD,), False, decision.REFRESH),
    ((compare.CHANGED,), True, decision.FULL_PULL),
])
def test_a_free_check_decides_without_the_judge(statuses, redesign, want):
    assert service.free_decision([check(s) for s in statuses], redesign) == want


class TestRun:
    @pytest.fixture
    def stubbed(self, monkeypatch):
        async def load(conn, slug):
            return [base(), base("https://a.org/contact", snapshot_id=8)], 0

        async def fetch_today(source, scratch):
            same = source.text_hash if source.url.endswith("contact") else "b" * 64
            return fetch_status.Today(source.url, fetch_status.OK, "HTTP 200", text="We fund 500 schools.",
                                      fingerprint=same)

        async def old_text(source):
            return "We fund 400 schools."

        async def none(*a):
            return None

        async def archive_all(checks, found):
            return {}

        monkeypatch.setattr(baseline, "load", load)
        monkeypatch.setattr(fetch_status, "fetch_today", fetch_today)
        monkeypatch.setattr("app.ingest.refresh.diff.old_text", old_text)
        monkeypatch.setattr(evidence, "load_findings", lambda conn, slug: _value({URL: ["We fund 400 schools."]}))
        monkeypatch.setattr(judge, "load_context", none)
        monkeypatch.setattr(discover, "load_subject", none)
        monkeypatch.setattr(save, "archive_all", archive_all)
        monkeypatch.setattr(service, "resolve_model", lambda spec: pytest.fail("a free check built a model"))

    async def test_a_free_run_saves_every_source_and_its_decision(self, stubbed):
        conn = ScriptConn()
        run_id = await service.run(ScriptPool(conn), SLUG, service.FREE, False, USER)
        [(_sql, start)] = conn.sql("INSERT INTO source_check_runs")
        assert start == (run_id, SLUG, service.FREE, USER)
        rows = [p for _s, p in conn.sql("INSERT INTO source_checks")]
        assert {(r[2], r[5]) for r in rows} == {(URL, compare.CHANGED), ("https://a.org/contact", compare.UNCHANGED)}
        changed = next(r for r in rows if r[2] == URL)
        assert changed[11:13] == (["We fund 400 schools."], ["We fund 500 schools."])
        [(_sql, finish)] = conn.sql("UPDATE source_check_runs SET decision")
        assert finish == (decision.REFRESH, None, None, run_id)

    async def test_nothing_to_compare_is_refused_before_a_run_starts(self, stubbed, monkeypatch):
        monkeypatch.setattr(baseline, "load", lambda conn, slug: _value(([], 1)))
        conn = ScriptConn()
        with pytest.raises(service.NoBaseline):
            await service.run(ScriptPool(conn), SLUG, service.FREE, False, USER)
        assert conn.sql("INSERT INTO source_check_runs") == []

    async def test_a_second_run_of_the_same_slug_waits(self, stubbed):
        conn = ScriptConn([("FROM source_check_runs", {"?column?": 1})])
        with pytest.raises(service.Busy):
            await service.run(ScriptPool(conn), SLUG, service.FREE, False, USER)

    async def test_a_failure_is_saved_on_the_run(self, stubbed, monkeypatch):
        async def boom(*a):
            raise RuntimeError("site down")

        monkeypatch.setattr(fetch_status, "fetch_today", boom)
        conn = ScriptConn()
        run_id = await service.run(ScriptPool(conn), SLUG, service.FREE, False, USER)
        [(_sql, failed)] = conn.sql("SET error")
        assert failed == ("RuntimeError: site down", run_id)

    async def test_a_full_run_saves_the_update_it_asked_for(self, stubbed, monkeypatch):
        async def stages(*a):
            return [check(compare.CHANGED)], discover.Discovery(), decision.REFRESH

        async def refresh(*a):
            return 91, "saved as entity_research #91"

        monkeypatch.setattr(service, "_stages", stages)
        monkeypatch.setattr(service, "_refresh", refresh)
        conn = ScriptConn()
        run_id = await service.run(ScriptPool(conn), SLUG, service.FULL, True, USER)
        [(_sql, finish)] = conn.sql("UPDATE source_check_runs SET decision")
        assert finish == (decision.REFRESH, 91, "saved as entity_research #91", run_id)

    async def test_no_update_unless_the_decision_is_refresh(self, stubbed, monkeypatch):
        async def stages(*a):
            return [check(compare.UNCHANGED)], discover.Discovery(), decision.NOTHING

        monkeypatch.setattr(service, "_stages", stages)
        monkeypatch.setattr(service, "_refresh", lambda *a: pytest.fail("updated with nothing to update"))
        conn = ScriptConn()
        await service.run(ScriptPool(conn), SLUG, service.FULL, True, USER)
        [(_sql, finish)] = conn.sql("UPDATE source_check_runs SET decision")
        assert finish[:3] == (decision.NOTHING, None, None)


async def test_the_baseline_view_counts_the_facts_each_source_holds(monkeypatch):
    monkeypatch.setattr(baseline, "load", lambda conn, slug: _value(([base(), base("https://a.org/x")], 2)))
    monkeypatch.setattr(evidence, "load_findings", lambda conn, slug: _value({URL: ["a", "b"]}))
    sources, unrecorded = await service.baseline_view(ScriptConn(), SLUG)
    assert [(s.url, s.facts, s.archived, s.read_on) for s in sources] == [
        (URL, 2, True, "2026-11-14"), ("https://a.org/x", 0, True, "2026-11-14")]
    assert unrecorded == 2


async def _value(v):
    return v


class TestRefresh:
    @pytest.fixture
    def refresh(self, monkeypatch):
        state = SimpleNamespace(asked=0, today=False)

        async def load(conn, slug):
            return {"slug": slug, "entity_name": "Funder", "canonical_name": None, "summary": "s"}, []

        async def researched_today(conn, slug):
            return state.today

        async def propose(model, grader, question):
            state.asked += 1
            return delta.Delta(summary="The CSR mailbox moved."), []
        monkeypatch.setattr(delta, "load", load)
        monkeypatch.setattr(delta, "researched_today", researched_today)
        monkeypatch.setattr(delta, "propose", propose)
        monkeypatch.setattr(delta, "save_row", lambda conn, *a: _value(91))
        monkeypatch.setattr(service, "resolve_model",
                            lambda spec: SimpleNamespace(with_structured_output=lambda schema, **kw: None))
        monkeypatch.setattr(brief, "publish", lambda *a, **kw: pytest.fail("published the brief before review"))
        return state

    async def run(self):
        return await service._refresh(ScriptPool(ScriptConn()), SLUG, [], discover.Discovery(),
                                      judge.Context((), ()), save.Saved(0, 0, 0))

    async def test_the_row_waits_in_review_and_the_brief_is_left_alone(self, refresh):
        row_id, summary = await self.run()
        assert row_id == 91 and "waits in Review & save" in summary and refresh.asked == 1

    async def test_researched_today_asks_no_model(self, refresh):
        refresh.today = True
        assert await self.run() == (None, "it was already researched today") and refresh.asked == 0


async def _value(v):
    return v

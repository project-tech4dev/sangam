"""The change check from the Scout screen: free stops before any model, every run is saved with its decision."""

from __future__ import annotations

import asyncio
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
    gap_search,
    judge,
    save,
    service,
)
from tests.cov_ingest_fakes import ScriptConn, ScriptPool

SLUG = "azim-premji-foundation"
RUN = UUID("00000000-0000-0000-0000-000000000001")
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
        assert conn.sql("INSERT INTO source_check_runs") == []

    async def test_the_busy_check_and_the_claim_run_under_one_lock(self, stubbed):
        conn = ScriptConn()
        await service.run(ScriptPool(conn), SLUG, service.FREE, False, USER)
        order = [sql for sql, _ in conn.calls if "advisory" in sql or "source_check_runs" in sql][:3]
        assert "pg_advisory_xact_lock" in order[0] and "finished_at IS NULL" in order[1]
        assert order[2].startswith("INSERT INTO source_check_runs")
        assert conn.sql("pg_advisory_xact_lock")[0][1] == (service.CHECK_LOCK, SLUG)

    async def test_a_failure_is_saved_on_the_run(self, stubbed, monkeypatch):
        async def boom(*a):
            raise RuntimeError("site down")

        monkeypatch.setattr(fetch_status, "fetch_today", boom)
        conn = ScriptConn()
        run_id = await service.run(ScriptPool(conn), SLUG, service.FREE, False, USER)
        [(_sql, failed)] = conn.sql("SET error")
        assert failed == ("RuntimeError: site down", run_id)

    async def test_a_stopped_turn_marks_the_run_cancelled(self, stubbed, monkeypatch):
        # Unmarked, the run reads as running and blocks every check of the slug for STALE_MINUTES.
        async def stopped(*a):
            raise asyncio.CancelledError

        monkeypatch.setattr(fetch_status, "fetch_today", stopped)
        conn = ScriptConn()
        with pytest.raises(asyncio.CancelledError):
            await service.run(ScriptPool(conn), SLUG, service.FREE, False, USER)
        [(_sql, failed)] = conn.sql("SET error")
        assert failed[0] == "cancelled"

    async def test_a_full_run_saves_the_update_it_asked_for(self, stubbed, monkeypatch):
        async def stages(*a, **kw):
            return [check(compare.CHANGED)], discover.Discovery(), decision.REFRESH

        async def refresh(*a):
            return 91, "saved as entity_research #91"

        monkeypatch.setattr(service, "stages", stages)
        monkeypatch.setattr(service, "_refresh", refresh)
        conn = ScriptConn()
        run_id = await service.run(ScriptPool(conn), SLUG, service.FULL, True, USER)
        [(_sql, finish)] = conn.sql("UPDATE source_check_runs SET decision")
        assert finish == (decision.REFRESH, 91, "saved as entity_research #91", run_id)

    async def test_the_run_is_one_trace_named_by_its_session(self, stubbed, monkeypatch):
        seen = {}

        async def traced_job(settings, name, work, **kw):
            seen.update(name=name, **kw)
            return await work()

        monkeypatch.setattr(service, "traced_job", traced_job)
        run_id = await service.run(ScriptPool(ScriptConn()), SLUG, service.FREE, False, USER,
                                   user_email="staff@sangam.org")
        assert seen == {"name": "sangam_source_check", "inputs": {"slug": SLUG, "depth": service.FREE, "refresh": False},
                        "session_id": f"source-check-{run_id}", "tags": ("source-check", service.FREE),
                        "user_id": "staff@sangam.org"}

    async def test_the_trace_records_what_the_check_found(self, stubbed, monkeypatch):
        outputs = []

        async def traced_job(settings, name, work, **kw):
            outputs.append(await work())
            return outputs[-1]

        monkeypatch.setattr(service, "traced_job", traced_job)
        await service.run(ScriptPool(ScriptConn()), SLUG, service.FREE, False, USER)
        [out] = outputs
        assert out["decision"] == decision.REFRESH and out["refresh_row_id"] is None
        assert set(out) == {"decision", "sources", "new_sources", "gap_sources", "source_checks_rows",
                            "refresh_row_id", "refresh_summary"}

    async def test_langfuse_is_set_up_and_flushed_once_even_when_the_check_fails(self, stubbed, monkeypatch):
        calls = []

        async def boom(*a, **kw):
            raise RuntimeError("site down")

        monkeypatch.setattr(service, "configure_langfuse", lambda settings: calls.append("configure"))
        monkeypatch.setattr(service, "flush_traces", lambda: calls.append("flush"))
        monkeypatch.setattr(service, "stages", boom)
        conn = ScriptConn()
        run_id = await service.run(ScriptPool(conn), SLUG, service.FREE, False, USER)
        assert calls == ["configure", "flush"]
        [(_sql, failed)] = conn.sql("SET error")
        assert failed == ("RuntimeError: site down", run_id)

    async def test_no_update_unless_the_decision_is_refresh(self, stubbed, monkeypatch):
        async def stages(*a, **kw):
            return [check(compare.UNCHANGED)], discover.Discovery(), decision.NOTHING

        monkeypatch.setattr(service, "stages", stages)
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


def _changed(url: str = "https://a.org/about", status: str = compare.CHANGED) -> compare.Check:
    base = baseline.Baseline(url, 7, "page", "a" * 64, "k", 31, date(2026, 11, 14))
    return compare.Check(base, fetch_status.Today(url, fetch_status.OK, "HTTP 200", text="Grants of 500."), status)


class TestUpdateRefused:
    @pytest.fixture
    def entity(self, monkeypatch):
        state = SimpleNamespace(row={"id": 5, "slug": SLUG, "status": "complete", "entity_kind": "funder"},
                                today=False)
        monkeypatch.setattr(delta, "load", lambda conn, slug: _value((state.row, [])))
        monkeypatch.setattr(delta, "researched_today", lambda conn, slug: _value(state.today))
        return state

    async def test_an_update_that_can_be_saved_is_not_refused(self, entity):
        assert await service.update_refused(ScriptPool(ScriptConn()), SLUG) is None

    async def test_researched_today_is_refused_up_front(self, entity):
        entity.today = True
        assert "already researched today" in await service.update_refused(ScriptPool(ScriptConn()), SLUG)

    async def test_no_research_or_research_that_found_nothing_is_refused(self, entity):
        entity.row = {**entity.row, "status": "not_found"}
        assert "found nothing" in await service.update_refused(ScriptPool(ScriptConn()), SLUG)
        entity.row = None
        assert "no research" in await service.update_refused(ScriptPool(ScriptConn()), SLUG)


class TestRefresh:
    @pytest.fixture
    def refresh(self, monkeypatch):
        state = SimpleNamespace(models=[], saved=[], reread=[], entity={"id": 5, "slug": SLUG, "entity_name": "Funder",
                                                                        "canonical_name": None, "summary": "s"})
        monkeypatch.setattr(delta, "load", lambda conn, slug: _value((state.entity, [])))
        monkeypatch.setattr(delta, "researched_today", lambda conn, slug: _value(False))

        def resolve(spec):
            state.models.append(spec)
            return SimpleNamespace(with_structured_output=lambda schema, **kw: _Structured(schema, kw))
        monkeypatch.setattr(service, "resolve_model", resolve)

        async def propose(model, grader, question):
            state.question, state.model, state.grader = question, model, grader
            return delta.Delta(summary="The CSR mailbox moved."), ["f1 should be an update"]
        monkeypatch.setattr(delta, "propose", propose)
        monkeypatch.setattr(delta, "apply", lambda proposed, srcs, *rest: delta.Applied(added=1, findings=[{"x": 1}]))

        async def save_row(conn, entity, applied, proposed, context, snapshot_ids, read, held_years=None):
            state.saved.append(read)
            return 91
        monkeypatch.setattr(delta, "save_row", save_row)
        monkeypatch.setattr(delta, "note_reread", lambda conn, row_id, ids: _value(state.reread.append((row_id, ids))))
        monkeypatch.setattr(brief, "publish", lambda *a, **kw: pytest.fail("published the brief before review"))
        return state

    async def run(self, checks=None, saved=None):
        return await service._refresh(ScriptPool(ScriptConn()), RUN, SLUG, [_changed()] if checks is None else checks,
                                      discover.Discovery(), judge.Context((), ()), saved or save.Saved(0, 0, 0))

    @pytest.mark.parametrize("entity, why", [
        ({"status": "not_found"}, "found nothing"), ({"entity_kind": "unknown"}, "funder or an NGO")])
    async def test_research_with_nothing_to_carry_is_not_refreshed(self, refresh, entity, why):
        refresh.entity = {**refresh.entity, **entity}
        row_id, summary = await self.run()
        assert row_id is None and why in summary and refresh.models == []

    async def test_only_gone_pages_ask_no_model(self, refresh):
        row_id, summary = await self.run([_changed(status=fetch_status.DEAD)])
        assert row_id is None and "only gone pages changed" in summary and refresh.models == []

    async def test_a_model_failure_saves_nothing_and_says_so(self, refresh, monkeypatch):
        async def propose(model, grader, question):
            raise ValueError("summary too short")
        monkeypatch.setattr(delta, "propose", propose)
        row_id, summary = await self.run()
        assert row_id is None and refresh.saved == [] and "no usable delta (ValueError)" in summary

    async def test_a_delta_that_changes_nothing_saves_no_row_but_moves_the_baseline(self, refresh, monkeypatch):
        monkeypatch.setattr(delta, "apply", lambda proposed, srcs, *rest: delta.Applied(kept=2))
        row_id, summary = await self.run(saved=save.Saved(0, 0, 0, {"https://a.org/about": 77}))
        assert row_id is None and refresh.saved == [] and refresh.reread == [(5, [77])]
        assert "the delta changes nothing" in summary

    async def test_a_page_with_an_unsettled_broken_fact_keeps_its_baseline(self, refresh, monkeypatch):
        stale = "https://a.org/stale"
        monkeypatch.setattr(delta, "apply", lambda proposed, srcs, *rest: delta.Applied(
            added=1, findings=[{"x": 1}], unhandled=["f2"], stale={stale}))
        await self.run([_changed(), _changed(stale)])
        assert refresh.saved == [["https://a.org/about"]]

    async def test_the_delta_is_asked_of_the_research_model_and_waits_in_review(self, refresh):
        row_id, summary = await self.run()
        settings = service.get_settings()
        assert refresh.models == [settings.research_model, settings.utility_model]
        assert (refresh.model.schema, refresh.model.kw, refresh.model.name) == (
            delta.Delta, {"method": "json_schema"}, "source-check/delta")
        assert (refresh.grader.schema, refresh.grader.kw, refresh.grader.name) == (delta.Grade, {}, "source-check/grade")
        assert refresh.question.startswith("Organisation: Funder")
        assert row_id == 91 and "waits in Review & save" in summary and "reviewer: f1 should be an update" in summary

    async def test_a_gap_page_is_read_but_never_joins_the_baseline(self, refresh, monkeypatch):
        saved_args = []
        gap = delta.Source("https://partner.org/report", discover.GAP, "text", hint={"fills": "csr_year"})
        mine = delta.Source("https://a.org/about", "changed", "text")
        monkeypatch.setattr(delta, "sources", lambda *a: [mine, gap])
        monkeypatch.setattr(delta, "save_row", lambda conn, *a: _value(saved_args.append(a) or 91))
        conn = ScriptConn()
        await service._refresh(ScriptPool(conn), RUN, SLUG, [], discover.Discovery(), judge.Context((), ()),
                               save.Saved(0, 0, 0, {mine.url: 55, gap.url: 56}))
        [(_entity, _applied, _proposed, _context, snapshot_ids, read, _years)] = saved_args
        assert snapshot_ids == [55] and read == [mine.url, gap.url]
        # Read by the update, it is not offered again until its text changes.
        [(_sql, params)] = conn.sql("UPDATE source_checks")
        assert params == (service.READ_BY_UPDATE, RUN, [gap.url])

    async def test_researched_today_asks_no_model(self, refresh, monkeypatch):
        monkeypatch.setattr(delta, "researched_today", lambda conn, slug: _value(True))
        assert await self.run() == (None, f"{SLUG}: no refresh: it was already researched today")
        assert refresh.models == []

    async def test_no_row_to_carry_forward_asks_nothing(self, refresh):
        refresh.entity = None
        assert await self.run() == (None, f"{SLUG}: no refresh: no research row to carry forward")
        assert refresh.models == []


async def test_a_full_check_searches_for_gaps_after_discovery_and_skips_what_it_found(monkeypatch, tmp_path):
    new = discover.Lead.of({"url": "https://a.org/new-report", "title": "t", "content": "c"})
    off = discover.Lead.of({"url": "https://csr.gov.in/a", "title": "t", "content": "c"})
    read = fetch_status.Today(off.url, fetch_status.OK, "HTTP 200", text="t", fingerprint="f" * 64)
    seen = {}

    async def fetch_today(source, scratch):
        return fetch_status.Today(source.url, fetch_status.OK, "HTTP 200", text="t",
                                  fingerprint="a" * 64 if source.url.endswith("contact") else "b" * 64)

    async def found_new(*a):
        return discover.Discovery(new=[(new, "report")], fetched={new.url: read})

    async def gaps(subject, known_urls, known_hashes, *rest):
        seen.update(urls=set(known_urls), hashes=set(known_hashes))
        return gap_search.GapSearch(leads=[(off, "csr_year", "a filing")], fetched={off.url: read})

    monkeypatch.setattr(fetch_status, "fetch_today", fetch_today)
    monkeypatch.setattr("app.ingest.refresh.diff.old_text", lambda source: _value("t"))
    specs: list[str] = []

    def resolve(spec):
        specs.append(spec)
        return SimpleNamespace(with_structured_output=lambda s: _Structured(s, {}))
    monkeypatch.setattr(service, "resolve_model", resolve)
    monkeypatch.setattr(judge, "run", lambda checks, *a: _value(checks))
    monkeypatch.setattr(discover, "run", found_new)
    monkeypatch.setattr(gap_search, "run", gaps)
    earlier = "https://partner.org/read-last-week"
    given = service.Inputs([base(), base("https://a.org/contact", snapshot_id=8)], 0, {}, judge.Context((), ()),
                           discover.Subject("A", "a.org"), frozenset({earlier}), frozenset({"e" * 64}))
    ended = await service.stages(SLUG, service.FULL, tmp_path, given)
    assert ended is not None
    _checks, found, verdict = ended
    assert new.url in seen["urls"] and earlier in seen["urls"] and {"f" * 64, "e" * 64} <= seen["hashes"]
    settings = service.get_settings()
    assert specs == [settings.source_check_judge_model, settings.source_check_gap_model]
    assert found.gap_leads == [(off, "csr_year", "a filing")] and decision.gap_sources(found) == 1
    assert verdict == decision.REFRESH


class _Structured:
    """A model's with_structured_output that remembers its schema and the step name with_config gave it."""

    def __init__(self, schema, kw):
        self.schema, self.kw, self.name = schema, kw, None

    def with_config(self, metadata):
        self.name = metadata[service.GENERATION_NAME]
        return self


async def test_the_inputs_include_pages_earlier_checks_read_for_a_gap(monkeypatch):
    monkeypatch.setattr(baseline, "load", lambda conn, slug: _value(([], 0)))
    monkeypatch.setattr(evidence, "load_findings", lambda conn, slug: _value({}))
    monkeypatch.setattr(judge, "load_context", lambda conn, slug: _value(judge.Context((), ())))
    monkeypatch.setattr(discover, "load_subject", lambda conn, slug: _value(None))
    conn = ScriptConn([("SELECT DISTINCT c.url", [{"url": "https://partner.org/a"}, {"url": "https://csr.gov.in/b"}]),
                       ("SELECT DISTINCT s.text_hash", [{"text_hash": "e" * 64}])])
    given = await service.load_inputs(conn, SLUG)
    assert given.gap_urls == {"https://partner.org/a", "https://csr.gov.in/b"} and given.gap_hashes == {"e" * 64}
    [(_sql, params)] = conn.sql("SELECT DISTINCT s.text_hash")
    assert params == (SLUG, service.READ_BY_UPDATE)
    # Only a page a saved research row cites counts as read; a look-only check's page may be offered again.
    sql = next(s for s, _ in conn.calls if "SELECT DISTINCT c.url" in s)
    assert "jsonb_array_elements(r.findings)" in sql and "f->>'source_url' = c.url" in sql

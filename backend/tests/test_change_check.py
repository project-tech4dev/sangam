"""make source-check: the command, and its first stage, the baseline."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.ingest import brief
from app.ingest.refresh import (
    baseline,
    change_check,
    compare,
    decision,
    delta,
    diff,
    discover,
    evidence,
    fetch_status,
    judge,
    save,
)
from tests.cov_ingest_fakes import ScriptConn, ScriptPool

SLUG = "azim-premji-foundation"
CONTACT = "https://a.org/contact"


def row(url: str, **over) -> dict:
    return {"url": url, "snapshot_id": 7, "kind": "page", "text_hash": "3fa91c0b2e7d" + "0" * 52,
            "archive_key": "3fa9/abc-about.md", "research_id": 31, "researched_on": date(2026, 11, 14), **over}


def test_a_slug_is_required(capsys):
    with pytest.raises(SystemExit):
        change_check.parse([])
    assert "--slug" in capsys.readouterr().err


def test_an_unknown_stage_names_the_ones_there_are(capsys):
    with pytest.raises(SystemExit):
        change_check.parse(["--slug", SLUG, "--until", "nonsense"])
    err = capsys.readouterr().err
    assert "invalid choice: 'nonsense'" in err and all(s in err for s in change_check.STAGES)


def test_write_runs_every_stage(capsys):
    assert change_check.parse(["--slug", SLUG, "--write"]).write
    assert not change_check.parse(["--slug", SLUG]).write
    with pytest.raises(SystemExit):
        change_check.parse(["--slug", SLUG, "--write", "--until", "judge"])
    assert "cannot stop early" in capsys.readouterr().err


def test_refresh_needs_write(capsys):
    assert change_check.parse(["--slug", SLUG, "--write", "--refresh"]).refresh
    with pytest.raises(SystemExit):
        change_check.parse(["--slug", SLUG, "--refresh"])
    assert "--refresh needs --write" in capsys.readouterr().err


def test_without_until_it_runs_every_stage():
    args = change_check.parse(["--slug", SLUG])
    assert (args.slug, args.until) == (SLUG, change_check.STAGES[-1])


class _Pool:
    async def open(self):
        pass

    async def close(self):
        self.closed = True

    def connection(self):
        return ScriptPool(ScriptConn()).connection()


class TestStages:
    @pytest.fixture
    def run(self, monkeypatch):
        fetched: list[str] = []

        async def load(conn, slug):
            return [baseline.Baseline(**row("https://a.org/about")), baseline.Baseline(**row(CONTACT))], 0

        async def fetch_today(source, scratch):
            # /about differs and /contact is as it was: one of two, so not a redesign.
            fetched.append(source.url)
            same = source.text_hash if source.url == CONTACT else None
            return fetch_status.Today(source.url, fetch_status.OK, "HTTP 200", fingerprint=same)
        monkeypatch.setattr(change_check, "make_pool", lambda url, max_size: _Pool())
        monkeypatch.setattr(baseline, "load", load)
        monkeypatch.setattr(fetch_status, "fetch_today", fetch_today)
        return fetched

    async def test_until_baseline_fetches_nothing(self, run, capsys):
        await change_check.main(SLUG, "baseline")
        assert run == [] and "2 sources to check" in capsys.readouterr().out

    async def test_until_fetch_fetches_each_source(self, run, capsys):
        await change_check.main(SLUG, "fetch")
        out = capsys.readouterr().out
        assert run == ["https://a.org/about", CONTACT] and "fetched 2 · 2 ok" in out and "unchanged" not in out

    async def test_until_hash_compares_each_source(self, run, capsys):
        await change_check.main(SLUG, "hash")
        assert f"{SLUG}: 2 sources · 1 differs · 1 unchanged" in capsys.readouterr().out

    async def test_until_diff_and_evidence(self, run, monkeypatch, capsys):
        async def old_text(source):
            return "We fund 400 schools."
        monkeypatch.setattr(diff, "old_text", old_text)
        await change_check.main(SLUG, "diff")
        out = capsys.readouterr().out
        assert "- We fund 400 schools." in out and "broken" not in out
        await change_check.main(SLUG, "evidence")
        assert "no facts cite this page" in capsys.readouterr().out

    async def test_until_evidence_builds_no_model(self, run, monkeypatch):
        monkeypatch.setattr(diff, "old_text", lambda source: _value("We fund 400 schools."))
        monkeypatch.setattr(change_check, "resolve_model", lambda spec: pytest.fail("built a model"))
        await change_check.main(SLUG, "evidence")

    async def test_until_judge_asks_the_model_once_per_page_that_differs(self, run, monkeypatch, capsys):
        asked: list = []

        async def ainvoke(messages):
            asked.append(messages)
            return judge.Judgement(meaningful=False, confidence="high", reason="only the wording")
        model = SimpleNamespace(ainvoke=ainvoke)
        monkeypatch.setattr(diff, "old_text", lambda source: _value("We fund 400 schools."))
        monkeypatch.setattr(change_check, "resolve_model",
                            lambda spec: SimpleNamespace(with_structured_output=lambda schema: model))
        await change_check.main(SLUG, "judge")
        out = capsys.readouterr().out
        assert len(asked) == 1 and "1 minor" in out and "(judge: not meaningful, high)" in out

    async def test_until_discover_searches_with_what_was_read(self, run, monkeypatch, capsys):
        seen: dict = {}

        async def ainvoke(messages):
            return judge.Judgement(meaningful=False, confidence="high", reason="only the wording")

        async def search(subject, known_urls, known_hashes, context, model, api_key, client, scratch):
            seen.update(urls=known_urls, hashes=known_hashes)
            return discover.Discovery(searched=3)
        monkeypatch.setattr(diff, "old_text", lambda source: _value("We fund 400 schools."))
        monkeypatch.setattr(change_check, "resolve_model", lambda spec: SimpleNamespace(
            with_structured_output=lambda schema: SimpleNamespace(ainvoke=ainvoke)))
        monkeypatch.setattr(discover, "run", search)
        # A row saved before snapshots cites a page that has no baseline; it was read all the same.
        monkeypatch.setattr(evidence, "load_findings", lambda conn, slug: _value({"https://a.org/old": ["Old."]}))
        await change_check.main(SLUG, "judge")
        assert seen == {}
        await change_check.main(SLUG, "discover")
        assert seen["urls"] == {"https://a.org/about", CONTACT, "https://a.org/old"}
        assert row("x")["text_hash"] in seen["hashes"]
        assert f"{SLUG}: 3 searches" in capsys.readouterr().out

    @pytest.mark.parametrize("write", [True, False])
    async def test_write_archives_then_saves_what_every_stage_found(self, run, monkeypatch, capsys, write):
        calls: list = []

        async def ainvoke(messages):
            return judge.Judgement(meaningful=True, confidence="high", reason="a new programme")

        async def archive_all(checks, found):
            calls.append(("archive", [c.status for c in checks]))
            return {"https://a.org/about": "key"}

        async def write_rows(conn, run_id, slug, checks, found, keys):
            calls.append(("write", slug, keys, found.searched))
            return save.Saved(rows=1, snapshots=1, archive_failed=0)
        monkeypatch.setattr(diff, "old_text", lambda source: _value("We fund 400 schools."))
        monkeypatch.setattr(change_check, "resolve_model", lambda spec: SimpleNamespace(
            with_structured_output=lambda schema: SimpleNamespace(ainvoke=ainvoke)))
        monkeypatch.setattr(discover, "run", lambda *a: _value(discover.Discovery(searched=3)))
        monkeypatch.setattr(save, "archive_all", archive_all)
        monkeypatch.setattr(save, "write", write_rows)
        await change_check.main(SLUG, "discover", write=write)
        if write:
            assert calls == [("archive", ["changed", "unchanged"]), ("write", SLUG, {"https://a.org/about": "key"}, 3)]
            assert f"{SLUG}: saved 1 source_checks rows · 1 new snapshots" in capsys.readouterr().out
        else:
            assert calls == []

    async def test_the_last_line_is_the_decision(self, run, monkeypatch, capsys):
        async def ainvoke(messages):
            return judge.Judgement(meaningful=False, confidence="high", reason="only the wording")
        monkeypatch.setattr(diff, "old_text", lambda source: _value("We fund 400 schools."))
        monkeypatch.setattr(change_check, "resolve_model", lambda spec: SimpleNamespace(
            with_structured_output=lambda schema: SimpleNamespace(ainvoke=ainvoke)))
        monkeypatch.setattr(discover, "run", lambda *a: _value(discover.Discovery(searched=3)))
        await change_check.main(SLUG, "discover")
        last = capsys.readouterr().out.strip().splitlines()[-1]
        assert last == f"{SLUG}: 2 sources · 1 minor · 1 unchanged → nothing to do"

    async def test_a_redesign_skips_the_judge_and_the_search(self, run, monkeypatch, capsys):
        async def load(conn, slug):
            return [baseline.Baseline(**row(f"https://a.org/{n}")) for n in range(4)], 0
        monkeypatch.setattr(baseline, "load", load)
        monkeypatch.setattr(diff, "old_text", lambda source: _value("We fund 400 schools."))
        monkeypatch.setattr(change_check, "resolve_model", lambda spec: pytest.fail("built a model"))
        monkeypatch.setattr(discover, "run", lambda *a: pytest.fail("searched"))
        await change_check.main(SLUG, "discover")
        out = capsys.readouterr().out
        assert "judge and discovery skipped" in out and out.strip().endswith("4 changed → full pull")

    @pytest.fixture
    def written(self, monkeypatch):
        """Every stage faked, the judge calling /about a change, and WRITE=1's own saving faked."""
        async def ainvoke(messages):
            return judge.Judgement(meaningful=True, confidence="high", reason="a new programme")
        monkeypatch.setattr(diff, "old_text", lambda source: _value("We fund 400 schools."))
        monkeypatch.setattr(change_check, "resolve_model", lambda spec: SimpleNamespace(
            with_structured_output=lambda schema, **kw: SimpleNamespace(ainvoke=ainvoke)))
        monkeypatch.setattr(discover, "run", lambda *a: _value(discover.Discovery(searched=3)))
        monkeypatch.setattr(save, "archive_all", lambda checks, found: _value({}))
        monkeypatch.setattr(save, "write", lambda *a: _value(save.Saved(2, 1, 0, {"https://a.org/about": 55})))
        refreshed: list = []
        monkeypatch.setattr(change_check, "_refresh", lambda *a: _value(refreshed.append(a)))
        return refreshed

    async def test_refresh_runs_only_when_the_decision_is_refresh(self, run, written, monkeypatch, capsys):
        await change_check.main(SLUG, "discover", write=True, refresh=True)
        assert len(written) == 1 and written[0][4].snapshot_ids == {"https://a.org/about": 55}
        monkeypatch.setattr(decision, "decide", lambda *a: decision.NOTHING)
        await change_check.main(SLUG, "discover", write=True, refresh=True)
        assert len(written) == 1 and f"{SLUG}: no refresh: the decision is nothing to do" in capsys.readouterr().out

    async def test_without_refresh_no_delta(self, run, written):
        await change_check.main(SLUG, "discover", write=True)
        assert written == []

    async def test_nothing_to_check_stops_before_fetching(self, run, monkeypatch, capsys):
        monkeypatch.setattr(baseline, "load", lambda conn, slug: _empty())
        await change_check.main(SLUG, "fetch")
        assert run == [] and "nothing to check" in capsys.readouterr().out


async def _value(v):
    return v


async def _empty():
    return [], 0


class TestLoad:
    async def test_it_reads_the_slug_and_maps_each_row(self):
        conn = ScriptConn([("DISTINCT ON (s.url)", [row("https://a.org/about")]), ("count(*)", {"n": 2})])
        found, unrecorded = await baseline.load(conn, SLUG)
        assert found == [baseline.Baseline(**row("https://a.org/about"))] and unrecorded == 2
        assert [p for _sql, p in conn.calls] == [(SLUG,), (SLUG,)]

    async def test_the_query_skips_wrong_entity_and_takes_the_newest_row(self):
        conn = ScriptConn()
        assert await baseline.load(conn, SLUG) == ([], 0)
        sql = conn.calls[0][0]
        assert "status <> 'wrong_entity'" in sql and "r.researched_on DESC, r.id DESC" in sql


class TestDescribe:
    def test_one_line_per_source(self):
        found = [baseline.Baseline(**row("https://a.org/about")),
                 baseline.Baseline(**row("https://a.org/ar.pdf", kind="document", archive_key=None))]
        out = baseline.describe(SLUG, found, 0).splitlines()
        assert out[0] == f"{SLUG}: 2 sources to check"
        assert out[1] == "  2026-11-14  page      3fa91c0b2e7d  archived  https://a.org/about"
        assert out[2].endswith("no archive  https://a.org/ar.pdf") and "document" in out[2]

    def test_nothing_recorded_says_what_to_do(self):
        out = baseline.describe(SLUG, [], 3)
        assert "nothing to check" in out and "Run a full pull first" in out
        assert "(3 research rows predate snapshots" in out


def _changed(url: str = "https://a.org/about", status: str = compare.CHANGED) -> compare.Check:
    base = baseline.Baseline(url, 7, "page", "a" * 64, "k", 31, date(2026, 11, 14))
    return compare.Check(base, fetch_status.Today(url, fetch_status.OK, "HTTP 200", text="Grants of 500."), status)


class TestRefresh:
    @pytest.fixture
    def refresh(self, monkeypatch):
        state = SimpleNamespace(models=[], saved=[], reread=[], entity={"id": 5, "slug": SLUG, "entity_name": "Funder",
                                                                        "canonical_name": None, "summary": "s"})
        monkeypatch.setattr(change_check, "make_pool", lambda url, max_size: _Pool())
        monkeypatch.setattr(delta, "load", lambda conn, slug: _value((state.entity, [])))

        def resolve(spec):
            state.models.append(spec)
            return SimpleNamespace(with_structured_output=lambda schema, **kw: (schema, kw))
        monkeypatch.setattr(change_check, "resolve_model", resolve)

        async def propose(model, grader, question):
            state.question, state.model, state.grader = question, model, grader
            return delta.Delta(summary="The CSR mailbox moved."), ["f1 should be an update"]
        monkeypatch.setattr(delta, "propose", propose)
        monkeypatch.setattr(delta, "apply", lambda proposed, srcs, kind: delta.Applied(added=1, findings=[{"x": 1}]))

        async def save_row(conn, entity, applied, proposed, context, snapshot_ids, read):
            state.saved.append(read)
            return 91
        monkeypatch.setattr(delta, "save_row", save_row)
        monkeypatch.setattr(delta, "note_reread", lambda conn, row_id, ids: _value(state.reread.append((row_id, ids))))
        monkeypatch.setattr(brief, "publish", lambda *a, **kw: pytest.fail("published the brief before review"))
        return state

    async def test_the_delta_is_asked_of_the_research_model_and_saved(self, refresh, capsys):
        await change_check._refresh(SLUG, [_changed()], discover.Discovery(), judge.Context((), ()),
                                    save.Saved(0, 0, 0))
        settings = change_check.get_settings()
        assert refresh.models == [settings.research_model, settings.utility_model]
        assert refresh.model == (delta.Delta, {"method": "json_schema"}) and refresh.grader == (delta.Grade, {})
        assert refresh.question.startswith("Organisation: Funder")
        out = capsys.readouterr().out
        assert "refresh saved as entity_research #91" in out and "reviewer: f1 should be an update" in out

    async def test_researched_today_asks_no_model(self, refresh, monkeypatch, capsys):
        monkeypatch.setattr(delta, "researched_today", lambda conn, slug: _value(True))
        await change_check._refresh(SLUG, [], discover.Discovery(), judge.Context((), ()), save.Saved(0, 0, 0))
        assert refresh.models == [] and "already researched today" in capsys.readouterr().out

    @pytest.mark.parametrize("entity, why", [
        ({"status": "not_found"}, "found nothing"), ({"entity_kind": "unknown"}, "funder or an NGO")])
    async def test_research_with_nothing_to_carry_is_not_refreshed(self, refresh, capsys, entity, why):
        refresh.entity = {**refresh.entity, **entity}
        await change_check._refresh(SLUG, [_changed()], discover.Discovery(), judge.Context((), ()),
                                    save.Saved(0, 0, 0))
        assert refresh.models == [] and why in capsys.readouterr().out

    async def test_only_gone_pages_ask_no_model(self, refresh, capsys):
        await change_check._refresh(SLUG, [_changed(status=fetch_status.DEAD)], discover.Discovery(),
                                    judge.Context((), ()), save.Saved(0, 0, 0))
        assert refresh.models == [] and "only gone pages changed" in capsys.readouterr().out

    async def test_a_model_failure_saves_nothing_and_says_so(self, refresh, monkeypatch, capsys):
        async def propose(model, grader, question):
            raise ValueError("summary too short")
        monkeypatch.setattr(delta, "propose", propose)
        await change_check._refresh(SLUG, [_changed()], discover.Discovery(), judge.Context((), ()),
                                    save.Saved(0, 0, 0))
        assert refresh.saved == [] and "no usable delta (ValueError)" in capsys.readouterr().out

    async def test_a_delta_that_changes_nothing_saves_no_row_but_moves_the_baseline(self, refresh, monkeypatch,
                                                                                      capsys):
        monkeypatch.setattr(delta, "apply", lambda proposed, srcs, kind: delta.Applied(kept=2))
        await change_check._refresh(SLUG, [_changed()], discover.Discovery(), judge.Context((), ()),
                                    save.Saved(0, 0, 0, {"https://a.org/about": 77}))
        assert refresh.saved == [] and refresh.reread == [(5, [77])]
        assert "the delta changes nothing" in capsys.readouterr().out

    async def test_a_page_with_an_unsettled_broken_fact_keeps_its_baseline(self, refresh, monkeypatch):
        stale = "https://a.org/stale"
        monkeypatch.setattr(delta, "apply", lambda proposed, srcs, kind: delta.Applied(
            added=1, findings=[{"x": 1}], unhandled=["f2"], stale={stale}))
        await change_check._refresh(SLUG, [_changed(), _changed(stale)], discover.Discovery(),
                                    judge.Context((), ()), save.Saved(0, 0, 0))
        assert refresh.saved == [["https://a.org/about"]]

    async def test_no_row_to_carry_forward_asks_nothing(self, refresh, capsys):
        refresh.entity = None
        await change_check._refresh(SLUG, [], discover.Discovery(), judge.Context((), ()), save.Saved(0, 0, 0))
        assert refresh.models == [] and "no research row to carry forward" in capsys.readouterr().out

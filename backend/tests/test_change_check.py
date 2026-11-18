"""make source-check: the command, and its first stage, the baseline."""

from __future__ import annotations

from datetime import date

import pytest

from app.ingest.refresh import baseline, change_check, diff, fetch_status
from tests.cov_ingest_fakes import ScriptConn, ScriptPool

SLUG = "azim-premji-foundation"


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
            return [baseline.Baseline(**row("https://a.org/about"))], 0

        async def fetch_today(source, scratch):
            fetched.append(source.url)
            return fetch_status.Today(source.url, fetch_status.OK, "HTTP 200")
        monkeypatch.setattr(change_check, "make_pool", lambda url, max_size: _Pool())
        monkeypatch.setattr(baseline, "load", load)
        monkeypatch.setattr(fetch_status, "fetch_today", fetch_today)
        return fetched

    async def test_until_baseline_fetches_nothing(self, run, capsys):
        await change_check.main(SLUG, "baseline")
        assert run == [] and "1 sources to check" in capsys.readouterr().out

    async def test_until_fetch_fetches_each_source(self, run, capsys):
        await change_check.main(SLUG, "fetch")
        out = capsys.readouterr().out
        assert run == ["https://a.org/about"] and "fetched 1 · 1 ok" in out and "unchanged" not in out

    async def test_until_hash_compares_each_source(self, run, capsys):
        await change_check.main(SLUG, "hash")
        assert f"{SLUG}: 1 sources · 1 differs" in capsys.readouterr().out

    async def test_until_diff_and_evidence(self, run, monkeypatch, capsys):
        async def old_text(source):
            return "We fund 400 schools."
        monkeypatch.setattr(diff, "old_text", old_text)
        await change_check.main(SLUG, "diff")
        out = capsys.readouterr().out
        assert "- We fund 400 schools." in out and "broken" not in out
        await change_check.main(SLUG, "evidence")
        assert "no facts cite this page" in capsys.readouterr().out

    async def test_nothing_to_check_stops_before_fetching(self, run, monkeypatch, capsys):
        monkeypatch.setattr(baseline, "load", lambda conn, slug: _empty())
        await change_check.main(SLUG, "fetch")
        assert run == [] and "nothing to check" in capsys.readouterr().out


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

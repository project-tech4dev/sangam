from __future__ import annotations

import asyncio
import csv
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ingest.catalog.matcher import Match
from app.ingest.pool import job, load, queue, worker


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


class FakeConn:
    """Replies by SQL substring; every statement is recorded."""

    def __init__(self, replies: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.replies = replies or {}
        self.executed: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> _Result:
        self.executed.append((sql, params))
        for needle, rows in self.replies.items():
            if needle in sql:
                return _Result(rows)
        return _Result([])

    @asynccontextmanager
    async def transaction(self):
        yield

    def ran(self, needle: str) -> list[Any]:
        return [p for s, p in self.executed if needle in s]


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn


def _row(**over: Any) -> dict[str, Any]:
    row = {"id": 1, "pool_funder_id": "acme--indian_csr", "category": "indian_csr", "name": "Acme Ltd", "cin": None,
           "signals": {}, "attempts": 1, "locked_by": "w1", "rank_in_category": 1}
    row.update(over)
    return row


class TestQueue:
    async def test_enabled_settings(self):
        conn = FakeConn({"funder_ingest_settings": [{"category": "indian_csr"}]})
        assert await queue.enabled_settings(conn) == [{"category": "indian_csr"}]

    async def test_no_free_slot_claims_nothing(self):
        conn = FakeConn({"AS free": [{"free": 0}]})
        assert await queue.claim(conn, "indian_csr", "w1") == []
        assert not conn.ran("UPDATE funder_pool SET ingest_status = 'running'")

    async def test_claims_up_to_the_free_slots(self):
        conn = FakeConn({"AS free": [{"free": 2}], "RETURNING *": [_row(), _row(id=2)]})
        rows = await queue.claim(conn, "indian_csr", "w1")
        assert len(rows) == 2
        assert conn.ran("RETURNING *")[0]["free"] == 2
        assert conn.ran("pg_advisory_xact_lock")[0] == ("funder_pool:indian_csr",)

    async def test_start_run_links_the_row(self):
        conn = FakeConn({"INSERT INTO ingest_runs": [{"id": 7}]})
        assert await queue.start_run(conn, _row()) == 7
        assert conn.ran("SET last_run_id")[0] == (7, 1)

    @pytest.mark.parametrize(("status", "run_status"), [("done", "finished"), ("failed", "failed"),
                                                         ("pending", "failed"), ("needs_review", "finished")])
    async def test_finish_ends_the_run_with_the_row(self, status, run_status):
        conn = FakeConn({"RETURNING last_run_id": [{"last_run_id": 9}]})
        await queue.finish(conn, _row(), status)
        assert conn.ran("UPDATE ingest_runs")[0] == (run_status, f" · {status}", 9)

    async def test_finish_leaves_a_reclaimed_row_alone(self):
        conn = FakeConn()
        await queue.finish(conn, _row(), "done")
        assert not conn.ran("UPDATE ingest_runs")

    async def test_finish_refunds_an_attempt_on_request(self):
        conn = FakeConn({"RETURNING last_run_id": [{"last_run_id": 9}]})
        await queue.finish(conn, _row(), "pending", refund=True)
        assert conn.ran("attempts = attempts - %s")[0][5] == 1

    @pytest.mark.parametrize(("attempts", "limit", "expected"), [(1, 3, "pending"), (3, 3, "failed")])
    async def test_fail_retries_until_the_attempts_are_used(self, attempts, limit, expected):
        conn = FakeConn({"max_attempts FROM": [{"max_attempts": limit}], "RETURNING last_run_id": [{"last_run_id": 9}]})
        assert await queue.fail(conn, _row(attempts=attempts), "boom") == expected

    async def test_fail_without_settings_uses_three_attempts(self):
        conn = FakeConn({"RETURNING last_run_id": [{"last_run_id": 9}]})
        assert await queue.fail(conn, _row(attempts=3), "boom") == "failed"
        assert await queue.fail(conn, _row(attempts=2), "boom") == "pending"


class TestProcess:
    @pytest.fixture
    def conn(self):
        return FakeConn({"INSERT INTO ingest_runs": [{"id": 7}], "RETURNING last_run_id": [{"last_run_id": 7}]})

    async def _no_research(self, row):
        raise AssertionError("researched a funder that Sangam already has")

    async def test_a_funder_already_in_sangam_is_skipped(self, conn, monkeypatch):
        async def resolve(c, name, cin=None, website=None):
            assert website == "acme.org"
            return Match("website", entity_id=5)

        monkeypatch.setattr(job, "resolve_funder", resolve)
        row = _row(signals={"website": "acme.org"})
        assert await job.process(FakePool(conn), row, self._no_research) == ("skipped", None)
        assert conn.ran("UPDATE funder_pool SET ingest_status")[0][0] == "skipped"

    async def test_a_close_name_goes_to_review_not_research(self, conn, monkeypatch):
        async def resolve(c, name, cin=None, website=None):
            return Match("trigram", score=0.8, candidates=[{"id": 3}])

        monkeypatch.setattr(job, "resolve_funder", resolve)
        status, error = await job.process(FakePool(conn), _row(), self._no_research)
        assert status == "needs_review" and "close name" in error
        assert conn.ran("INSERT INTO resolution_queue")

    @pytest.fixture
    def unmatched(self, monkeypatch):
        async def resolve(c, name, cin=None, website=None):
            return Match("none")

        async def no_holder(c, cin):
            return None

        monkeypatch.setattr(job, "resolve_funder", resolve)
        monkeypatch.setattr(job, "cin_holder", no_holder)

    async def test_saved_research_is_done_and_linked_to_the_run(self, conn, unmatched):
        conn.replies["FROM entity_research r"] = [
            {"slug": "acme-ltd", "entity_name": "Acme Ltd", "status": "complete", "cin": "L1"}]

        async def research(row):
            return [{"slug": "acme-ltd"}]

        assert await job.process(FakePool(conn), _row(), research) == ("done", None)
        assert conn.ran("SET run_id")[0] == (7, ["acme-ltd"])
        assert conn.ran("UPDATE funder_pool SET ingest_status")[0][2] == "L1"

    async def test_no_researcher_falls_back_to_the_earlier_research(self, conn, unmatched):
        conn.replies["SELECT slug FROM entity_research"] = [{"slug": "acme-old"}]
        conn.replies["FROM entity_research r"] = [
            {"slug": "acme-old", "entity_name": "Acme Ltd", "status": "partial", "cin": None}]

        async def research(row):
            return []

        assert (await job.process(FakePool(conn), _row(), research))[0] == "done"
        assert conn.ran("SET run_id")[0] == (7, ["acme-old"])

    async def test_research_that_saved_nothing_raises(self, conn, unmatched):
        async def research(row):
            return []

        with pytest.raises(RuntimeError, match="saved nothing"):
            await job.process(FakePool(conn), _row(), research)

    async def test_a_cin_held_by_another_funder_waits_for_review(self, conn, monkeypatch, unmatched):
        async def holder(c, cin):
            return {"id": 4, "name": "Other Ltd"}

        monkeypatch.setattr(job, "cin_holder", holder)
        conn.replies["FROM entity_research r"] = [
            {"slug": "acme-ltd", "entity_name": "Acme Ltd", "status": "complete", "cin": "L1"}]

        async def research(row):
            return [{"slug": "acme-ltd"}]

        status, error = await job.process(FakePool(conn), _row(), research)
        assert status == "needs_review" and "[funder:4]" in error

    def test_research_that_did_not_find_the_funder_says_why(self):
        assert job.verdict({"status": "not_found"}) == ("needs_review", "research ended not_found")


class TestUntilDone:
    def _scout(self, states):
        scout = worker.Scout.__new__(worker.Scout)
        calls = []

        async def ainvoke(arg, config=None):
            calls.append(arg)
            return states.pop(0)

        scout.graph = SimpleNamespace(ainvoke=ainvoke)
        scout.calls = calls
        return scout

    @staticmethod
    def _pause(*names):
        return {"__interrupt__": [SimpleNamespace(value={"action_requests": [{"name": n} for n in names]})]}

    async def test_a_run_with_no_pause_returns_its_summaries(self):
        scout = self._scout([{"messages": []}])
        assert await scout._until_done("go", {}) == []

    async def test_the_sources_pause_is_answered_with_public_web_and_library(self):
        scout = self._scout([self._pause("choose_sources"), {"messages": []}])
        await scout._until_done("go", {})
        decision = scout.calls[1].resume["decisions"][0]
        assert decision["edited_action"]["args"] == worker.SOURCES

    async def test_any_other_pause_is_refused(self):
        scout = self._scout([self._pause("save_funder")])
        with pytest.raises(RuntimeError, match="never answers"):
            await scout._until_done("go", {})

    async def test_endless_pauses_give_up(self):
        scout = self._scout([self._pause("choose_sources")] * 4)
        with pytest.raises(RuntimeError, match="kept pausing"):
            await scout._until_done("go", {})

    async def test_research_runs_as_staff_and_returns_the_summaries(self, monkeypatch):
        from langgraph.checkpoint.memory import InMemorySaver

        scout = worker.Scout.__new__(worker.Scout)
        scout.saver = InMemorySaver()

        async def until_done(text, config):
            return [{"slug": "acme"}]

        monkeypatch.setattr(scout, "_until_done", until_done)
        assert await scout.research(_row()) == [{"slug": "acme"}]
        assert worker.chat_scope.get().is_staff


class TestRunOne:
    @pytest.fixture(autouse=True)
    def _quiet_traces(self, monkeypatch):
        monkeypatch.setattr(worker, "flush_traces", lambda: None)

    async def test_a_processed_row_is_logged(self, monkeypatch):
        async def process(pool, row, research):
            return "done", None

        monkeypatch.setattr(worker.job, "process", process)
        await worker.run_one(FakePool(FakeConn()), _row(), None)

    async def test_a_raised_error_fails_the_attempt_not_the_worker(self, monkeypatch):
        async def process(pool, row, research):
            raise ValueError("bad page")

        failed = []

        async def fail(conn, row, error):
            failed.append(error)
            return "pending"

        monkeypatch.setattr(worker.job, "process", process)
        monkeypatch.setattr(worker.queue, "fail", fail)
        await worker.run_one(FakePool(FakeConn()), _row(), None)
        assert failed == ["ValueError: bad page"]

    async def test_a_cancelled_row_goes_back_to_pending_with_its_attempt(self, monkeypatch):
        async def process(pool, row, research):
            raise asyncio.CancelledError

        calls = []

        async def finish(conn, row, status, **kw):
            calls.append((status, kw))

        monkeypatch.setattr(worker.job, "process", process)
        monkeypatch.setattr(worker.queue, "finish", finish)
        with pytest.raises(asyncio.CancelledError):
            await worker.run_one(FakePool(FakeConn()), _row(), None)
        assert calls[0][0] == "pending" and calls[0][1]["refund"] is True


class TestTick:
    async def test_claimed_rows_start_at_once(self, monkeypatch):
        started = []

        async def run_one(pool, row, research):
            started.append(row["id"])

        async def settings(conn):
            return [{"category": "indian_csr"}, {"category": "global"}]

        async def claim(conn, category, worker_id):
            if category == "global":
                raise RuntimeError("db blip")
            return [_row(), _row(id=2)]

        monkeypatch.setattr(worker, "run_one", run_one)
        monkeypatch.setattr(worker.queue, "enabled_settings", settings)
        monkeypatch.setattr(worker.queue, "claim", claim)
        running: set[asyncio.Task] = set()
        await worker.tick(FakePool(FakeConn()), "w1", None, running)
        await asyncio.gather(*running)
        assert started == [1, 2] and not running

    async def test_nothing_enabled_claims_nothing(self, monkeypatch):
        async def settings(conn):
            return []

        monkeypatch.setattr(worker.queue, "enabled_settings", settings)
        running: set[asyncio.Task] = set()
        await worker.tick(FakePool(FakeConn()), "w1", None, running)
        assert not running


class TestLoad:
    def _write(self, path: Path, rows: list[dict[str, str]]) -> Path:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=load.COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_read_rows_reads_every_line(self, tmp_path):
        rows = [{c: "" for c in load.COLUMNS} | {"pool_funder_id": pid, "category": "indian_csr", "name": "Acme",
                                                  "rank_in_category": "1", "export_version": "v1"}
                for pid in ("a--indian_csr", "b--indian_csr")]
        path = self._write(tmp_path / "pool.csv", rows)
        assert len(load.read_rows(path)) == 2

    async def test_load_counts_inserted_and_updated(self):
        class Cursor:
            def __init__(self):
                self.sets = [[{"inserted": True}], [{"inserted": False}], [{"inserted": True}]]

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def executemany(self, sql, rows, returning=False):
                assert returning

            async def fetchone(self):
                return self.sets[0][0]

            def nextset(self):
                self.sets.pop(0)
                return bool(self.sets)

        class Conn(FakeConn):
            def cursor(self):
                return Cursor()

        conn = Conn({"GROUP BY": [{"category": "indian_csr", "ingest_status": "pending", "n": 3}]})
        inserted, updated, counts = await load.load(FakePool(conn), [(), (), ()])
        assert (inserted, updated) == (2, 1) and counts[0]["n"] == 3

    async def test_main_prints_the_counts(self, tmp_path, monkeypatch, capsys):
        closed = []

        class Pool:
            async def open(self):
                pass

            async def close(self):
                closed.append(True)

        async def fake_load(pool, rows):
            return 1, 0, [{"category": "indian_csr", "ingest_status": "pending", "n": 1}]

        monkeypatch.setattr(load, "read_rows", lambda path: [()])
        monkeypatch.setattr(load, "get_settings", lambda: SimpleNamespace(database_url="postgresql://x"))
        monkeypatch.setattr(load, "make_pool", lambda url, max_size=None: Pool())
        monkeypatch.setattr(load, "load", fake_load)
        assert await load.main(tmp_path / "pool.csv") == 0
        assert "1 inserted, 0 updated" in capsys.readouterr().out and closed

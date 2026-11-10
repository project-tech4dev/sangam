"""Public research's supervisor: each researcher gets the run's task, its line on the card, and the run's guards."""

import asyncio
from datetime import UTC, datetime

import pytest
from langchain_core.messages import ToolMessage

from app.proposals import readers
from app.proposals.middleware import LABEL, PUBLIC_RUN, PublicRun, ResearchProgress

ADMIN = {"id": "5", "name": "Admin"}


class Req:
    def __init__(self, call):
        self.tool_call = call

    def override(self, tool_call):
        return Req(tool_call)


def task(description="Dropout in Kiphire\nThe problem and the place."):
    return Req({"name": "task", "id": "c1", "args": {"description": description, "subagent_type": "public-researcher"}})


@pytest.fixture
def run():
    seen: list[list[dict]] = []
    held = PublicRun(avoid=("SeSTA",), task="Where it works: Kiphire, Nagaland")

    async def report():
        seen.append([dict(s) for s in held.slices])
    held.report = report
    token = PUBLIC_RUN.set(held)
    yield held, seen
    PUBLIC_RUN.reset(token)


class TestResearchProgress:
    async def test_a_researcher_gets_its_angle_and_the_runs_task(self, run):
        sent = []

        async def handler(req):
            sent.append(req.tool_call["args"]["description"])
            return ToolMessage("added 6 facts", tool_call_id="c1")
        await ResearchProgress().awrap_tool_call(task(), handler)
        assert sent == ["Dropout in Kiphire\nThe problem and the place.\n\nWhere it works: Kiphire, Nagaland"]

    async def test_its_line_runs_then_is_done(self, run):
        _, seen = run

        async def handler(req):
            return ToolMessage("added 6 facts", tool_call_id="c1")
        await ResearchProgress().awrap_tool_call(task(), handler)
        assert seen == [[{"label": "Dropout in Kiphire", "status": "running"}],
                        [{"label": "Dropout in Kiphire", "status": "done"}]]

    async def test_an_error_reply_marks_it_failed(self, run):
        held, _ = run

        async def handler(req):
            return ToolMessage("task failed", tool_call_id="c1", status="error")
        await ResearchProgress().awrap_tool_call(task(), handler)
        assert held.slices[0]["status"] == "failed"

    async def test_a_raise_marks_it_failed_and_still_raises(self, run):
        held, _ = run

        async def handler(req):
            raise RuntimeError("boom")
        with pytest.raises(RuntimeError):
            await ResearchProgress().awrap_tool_call(task(), handler)
        assert held.slices[0]["status"] == "failed"

    async def test_a_long_title_is_cut_and_a_heading_mark_dropped(self, run):
        held, _ = run

        async def handler(req):
            return ToolMessage("ok", tool_call_id="c1")
        await ResearchProgress().awrap_tool_call(task("## " + "x" * 200), handler)
        assert held.slices[0]["label"] == "x" * LABEL

    async def test_a_failed_write_never_fails_the_research(self, run):
        held, _ = run

        async def broken():
            raise ConnectionError("pool closed")
        held.report = broken

        async def handler(req):
            return ToolMessage("ok", tool_call_id="c1")
        result = await ResearchProgress().awrap_tool_call(task(), handler)
        assert result.content == "ok" and held.slices[0]["status"] == "done"

    async def test_other_tools_and_other_runs_pass_through(self, run):
        async def handler(req):
            return req.tool_call["args"]
        assert await ResearchProgress().awrap_tool_call(
            Req({"name": "read_file", "args": {"path": "/a"}}), handler) == {"path": "/a"}
        PUBLIC_RUN.set(None)
        assert await ResearchProgress().awrap_tool_call(task("x"), handler) == {
            "description": "x", "subagent_type": "public-researcher"}

    async def test_researchers_at_once_share_one_run(self, run):
        held, _ = run

        async def researcher(url):
            PUBLIC_RUN.get().pages[url] = "text"
        await asyncio.gather(researcher("a.gov.in"), researcher("b.gov.in"))
        assert set(held.pages) == {"a.gov.in", "b.gov.in"}


class TestProgressOnTheCard:
    def save_into(self, monkeypatch, work):
        async def save(pool, proposal_id, change):
            applied = change(work, "t")
            work.clear()
            work.update(applied.work)
        monkeypatch.setattr(readers.repo, "save", save)
        monkeypatch.setattr(readers, "get_pool", lambda: None)

    async def test_lines_go_on_the_running_mark_and_keep_its_start(self, monkeypatch):
        at = datetime(2026, 10, 22, 6, 0, tzinfo=UTC).isoformat()
        work = {"readers": {"public": {"status": "running", "at": at, "by": ADMIN, "title": "Public research"}}}
        self.save_into(monkeypatch, work)
        run = PublicRun(avoid=(), slices=[{"label": "Dropout in Kiphire", "status": "running"}])
        await readers._progress(6, run, ADMIN)
        assert work["readers"]["public"] == {"status": "running", "at": at, "by": ADMIN, "title": "Public research",
                                             "slices": [{"label": "Dropout in Kiphire", "status": "running"}]}

    async def test_a_finished_or_deleted_run_is_left_alone(self, monkeypatch):
        done = {"readers": {"public": {"status": "done", "at": "2026-10-22T06:00:00+00:00", "title": "P"}}}
        for work in (done, {}):
            before = repr(work)
            self.save_into(monkeypatch, work)
            await readers._progress(6, PublicRun(avoid=(), slices=[{"label": "x", "status": "done"}]), ADMIN)
            assert repr(work) == before

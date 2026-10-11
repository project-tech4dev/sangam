"""The run's sources: one pause where a person picks what Import reads, enforced on every subagent's reads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.ingest import run_sources
from app.ingest.agent import INTERRUPT_ON
from app.ingest.middleware import ChosenSources, RunSources
from app.ingest.run_sources import Sources
from app.ingest.tools import library_tools, pipeline_tools
from tests.test_import_roles import MEMBER, STAFF, STEWARD, _Pool, running_as


def _call(args: dict) -> dict:
    return {"name": "choose_sources", "args": args, "id": "c1", "type": "tool_call"}


async def _choose(args: dict, scope=STAFF) -> ToolMessage:
    with running_as(scope):
        return await pipeline_tools.choose_sources.ainvoke(_call(args))


def _answered(artifact=None, status="success") -> list:
    return [AIMessage("", tool_calls=[_call({})]),
            ToolMessage("chosen", tool_call_id="c1", name="choose_sources", artifact=artifact, status=status)]


class TestThePause:
    def test_choose_sources_pauses_before_reading_and_run_import_now_before_writing(self):
        assert set(INTERRUPT_ON) == {"choose_sources", "run_import_now"}
        assert "reject" in INTERRUPT_ON["choose_sources"]["allowed_decisions"]
        assert "edit" not in INTERRUPT_ON["run_import_now"]["allowed_decisions"]


class TestChooseSources:
    @pytest.fixture(autouse=True)
    def no_db(self, monkeypatch):
        monkeypatch.setattr(pipeline_tools, "get_pool", lambda: _Pool())

    async def test_web_and_library_need_no_files(self):
        out = await _choose({"web": True, "library": True}, MEMBER)
        assert out.artifact == {"web": True, "library": True, "vault_org": None, "vault_docs": [], "staff_docs": []}

    async def test_team_spreadsheets_are_staff_only(self):
        out = await _choose({"staff_paths": ["staff-sources/a.xlsx"]}, STEWARD)
        assert out.content.startswith("REFUSED") and out.artifact is None

    async def test_nothing_chosen_is_refused(self):
        out = await _choose({"web": False, "library": False})
        assert out.content.startswith("REFUSED") and out.artifact is None

    async def test_another_orgs_vault_is_refused(self):
        out = await _choose({"vault_org": 99, "vault_docs": [5]}, MEMBER)
        assert out.content.startswith("REFUSED") and out.artifact is None

    async def test_staff_paths_are_registered(self, monkeypatch):
        async def register(pool, path):
            return 41
        monkeypatch.setattr(pipeline_tools.staff_sources, "check_pick", lambda p: ("staff-sources", "a.xlsx", "A"))
        monkeypatch.setattr(pipeline_tools.staff_sources, "register", register)
        out = await _choose({"web": False, "library": False, "staff_paths": ["staff-sources/a.xlsx"]})
        assert out.artifact["staff_docs"] == [41] and "document 41" in out.content


class TestTheAnswerIsRead:
    def test_an_answer_is_the_runs_sources(self):
        assert run_sources.chosen(_answered({"web": False, "library": True})) == Sources(web=False, library=True)

    def test_a_rejected_card_means_public_websites_only(self):
        assert run_sources.chosen(_answered(status="error")) == run_sources.WEB_ONLY

    def test_a_refused_choice_is_no_answer(self):
        assert run_sources.chosen(_answered()) is None
        assert run_sources.chosen([]) is None


class TestReadsOutsideTheChoiceRefuse:
    CHOSEN = Sources(web=False, library=True, vault_org=7, vault_docs=frozenset({12}), staff_docs=frozenset({3}))

    @pytest.mark.parametrize(("name", "args", "allowed"), [
        ("read_page", {"url": "https://example.org"}, False),
        ("read_library_document", {"document_id": 1}, True),
        ("read_source_rows", {"name": "x", "documents": [3]}, True),
        ("read_source_rows", {"name": "x", "documents": [3, 4]}, False),
        ("read_source_rows", {"name": "x"}, False),
        ("read_vault_document", {"document_id": 12}, True),
        ("read_vault_document", {"document_id": 13}, False),
        ("save_research", {}, True),
    ])
    def test_per_tool(self, name, args, allowed):
        assert (run_sources.refusal(self.CHOSEN, name, args) is None) is allowed

    def test_nothing_chosen_reads_nothing(self):
        assert run_sources.refusal(None, "search_public_sources", {})
        assert run_sources.refusal(None, "save_research", {}) is None

    async def test_the_subagent_middleware_reads_the_supervisors_answer(self):
        request = SimpleNamespace(tool_call={"name": "read_page", "args": {}, "id": "r"})

        async def handler(r):
            return "read"

        assert isinstance(await RunSources().awrap_tool_call(request, handler), ToolMessage)
        token = run_sources.CURRENT.set(Sources(web=True))
        try:
            assert await RunSources().awrap_tool_call(request, handler) == "read"
        finally:
            run_sources.CURRENT.reset(token)


class TestNoSubagentBeforeTheAnswer:
    @staticmethod
    def task(messages):
        return SimpleNamespace(tool_call={"name": "task", "args": {}, "id": "t"}, state={"messages": messages})

    async def test_a_subagent_waits_for_the_answer(self):
        async def handler(r):
            pytest.fail("launched before the person answered")

        out = await ChosenSources().awrap_tool_call(self.task([]), handler)
        assert isinstance(out, ToolMessage) and "choose_sources first" in out.content

    async def test_a_subagent_carries_the_answer(self):
        seen = {}

        async def handler(r):
            seen["sources"] = run_sources.CURRENT.get()
            return "done"

        assert await ChosenSources().awrap_tool_call(self.task(_answered({"web": True})), handler) == "done"
        assert seen["sources"] == Sources(web=True) and run_sources.CURRENT.get() is None


class TestTheLibraryIsPublicOnly:
    async def test_a_document_without_a_public_archived_copy_is_not_read(self, monkeypatch):
        monkeypatch.setattr(library_tools, "get_pool", lambda: _Pool())
        out = await library_tools.read_library_document.ainvoke({"document_id": 5})
        assert "no archived copy" in out

    async def test_the_query_asks_for_public_rows(self, monkeypatch):
        pool = _Pool()
        monkeypatch.setattr(library_tools, "get_pool", lambda: pool)
        await library_tools.read_library_document.ainvoke({"document_id": 5})
        assert "is_public" in pool.conn.sql[0]

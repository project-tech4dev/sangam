"""The readers' code-only safeguards: their tools, the one file each may open, the lock on reading, step 2's exit."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings
from app.core.security import CallerScope
from app.ingest import run_sources
from app.proposals import context, readers, steps
from app.proposals import facts as fact_rules
from app.proposals import work as rules

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
ADMIN = {"id": str(UUID(int=5)), "name": "Admin"}


def reader(status, minutes_ago=1):
    return {"status": status, "at": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "by": ADMIN, "title": "Workplan"}


def proposal(work):
    return context.Current(id=1, title="t", org_id=7, org_name="SeSTA", funder_id=3, funder_name="ABF", work=work,
                           scope=CallerScope(UUID(int=5), False, {7: "admin"}), can_edit=True)


@pytest.fixture(scope="module")
def built():
    from app.proposals.agent import build_proposal_agent

    build_proposal_agent(Settings(tavily_api_key="test"), InMemorySaver())
    return readers.BUILT


class TestPublicResearch:
    def test_it_runs_only_its_tools(self, built):
        assert set(built.public.nodes["tools"].bound.tools_by_name) == {
            "search_public_sources", "read_page", "fetch_document", "read_document_pages", "add_facts", "read_file"}

    def test_it_never_asks_or_writes(self, built):
        assert not set(built.public.nodes["tools"].bound.tools_by_name) & {"ask_user", "task", "write_file", "execute"}

    def test_without_a_search_key_it_is_not_built(self, built):
        from app.proposals.agent import EVIDENCE_TOOLS, FUNDER_TOOLS, PUBLIC_TOOLS

        try:
            readers.build(Settings(tavily_api_key=""), EVIDENCE_TOOLS, FUNDER_TOOLS, PUBLIC_TOOLS)
            assert readers.BUILT.public is None
        finally:
            readers.build(Settings(tavily_api_key="test"), EVIDENCE_TOOLS, FUNDER_TOOLS, PUBLIC_TOOLS)

    def test_it_is_read_with_the_files_only_when_built(self):
        assert readers.pending({"sources": [41]}, NOW) == ["41", "funder"]
        assert readers.pending({"sources": [41]}, NOW, public=True) == ["41", "funder", "public"]

    def test_try_again_retries_it_alone(self):
        work = {"sources": [41], "readers": {"41": reader("done"), "funder": reader("done"), "public": reader("failed")}}
        assert readers.pending(work, NOW, public=True) == ["public"]

    def test_it_reads_the_web_and_no_file(self):
        mine = readers.sources_for(proposal({"sources": [41]}), readers.PUBLIC)
        assert run_sources.refusal(mine, "search_public_sources", {"query": "dropout Udalguri"}) is None
        assert run_sources.refusal(mine, "read_vault_document", {"document_id": 41}).startswith("REFUSED")

    def test_its_task_holds_no_figure_from_the_files(self):
        held = fact_rules.make({"subject": "adolescents out of school", "value": "38%", "origin": "vault",
                                "document_id": 41, "page": 3, "section": "A3"})
        p = proposal({"sources": [41], "facts": {"k1": held}})
        task = readers.public_task(p, ["Udalguri, Assam"], ["Education › School retention"], ["Girls' learning"], [])
        assert "38%" not in task and "Udalguri, Assam" in task
        assert task.count("SeSTA") == 1 and "Never search for SeSTA" in task

    def test_no_place_on_record_searches_the_state(self):
        assert "no place on record" in readers.public_task(proposal({}), [], [], [], [])

    def test_only_sangam_pitch_marks_it(self):
        with pytest.raises(rules.BadChange):
            rules.apply({}, {"readers.public": reader("done")}, by=ADMIN)
        assert rules.apply({}, {"readers.public": reader("done")}, by=ADMIN, via="agent").work[
            "readers"]["public"]["status"] == "done"


class TestPublicGuard:
    @staticmethod
    def call(name, args):
        from types import SimpleNamespace

        return SimpleNamespace(tool_call={"name": name, "args": args, "id": "c1"})

    async def run(self, name, args, reply="ok", files=None):
        from langchain_core.messages import ToolMessage

        from app.proposals.middleware import PUBLIC_RUN, PublicGuard, PublicRun

        state = PublicRun(avoid=("SeSTA",), files=files or {})
        ran = []

        async def handler(request):
            ran.append(request)
            return ToolMessage(reply, tool_call_id="c1", name=name)

        token = PUBLIC_RUN.set(state)
        try:
            result = await PublicGuard().awrap_tool_call(self.call(name, args), handler)
        finally:
            PUBLIC_RUN.reset(token)
        return result, ran, state

    async def test_a_search_naming_the_org_is_refused(self):
        result, ran, _ = await self.run("search_public_sources", {"query": "SeSTA dropout programme"})
        assert result.content.startswith("REFUSED") and not ran

    async def test_a_search_for_the_place_and_problem_runs(self):
        _, ran, _ = await self.run("search_public_sources", {"query": "dropout Udalguri UDISE+"})
        assert ran

    async def test_a_word_inside_another_is_not_the_org(self):
        _, ran, _ = await self.run("search_public_sources", {"query": "SeSTAR dropout"})
        assert ran

    async def test_each_page_read_is_kept_for_the_quote_check(self):
        _, _, state = await self.run("read_page", {"url": "https://udiseplus.gov.in/udalguri"}, reply="19.8 per cent")
        assert state.pages == {"udiseplus.gov.in/udalguri": "19.8 per cent"}

    def test_a_page_cited_with_www_or_a_slash_is_the_page_read(self):
        from app.proposals.middleware import page_key

        assert page_key("https://www.a.gov.in/report/") == page_key("http://a.gov.in/report")

    async def test_a_pdf_read_by_its_unsanitised_name_is_kept_under_its_url(self):
        files = {"NFHS_5_Assam.pdf": "rchiips.org/nfhs/assam.pdf"}
        _, _, state = await self.run("read_document_pages", {"filename": "NFHS 5 Assam.pdf"}, reply="anaemia 65.9",
                                     files=files)
        assert state.pages == {"rchiips.org/nfhs/assam.pdf": "\nanaemia 65.9"}

    async def test_a_refused_page_is_not_kept(self):
        _, _, state = await self.run("read_page", {"url": "https://x.org/a"}, reply="REFUSED: robots.txt")
        assert state.pages == {}


class TestEachReaderRunsOnlyItsTools:
    def test_the_file_reader(self, built):
        assert set(built.evidence.nodes["tools"].bound.tools_by_name) == {
            "read_vault_document", "read_brief", "add_facts", "read_file"}

    def test_the_funder_reader(self, built):
        assert set(built.funder.nodes["tools"].bound.tools_by_name) == {
            "read_brief", "list_funder_documents", "read_funder_document", "read_template", "add_facts", "read_file"}

    @pytest.mark.parametrize("which", ["evidence", "funder"])
    def test_no_reader_reads_the_web_or_asks(self, built, which):
        tools = set(getattr(built, which).nodes["tools"].bound.tools_by_name)
        assert not tools & (run_sources.WEB_TOOLS | {"ask_user", "task", "write_file", "execute"})


class TestEachFileReaderOpensOnlyItsFile:
    def test_another_ticked_file_is_refused(self):
        mine = readers.sources_for(proposal({"sources": [41, 42]}), "41")
        assert run_sources.refusal(mine, "read_vault_document", {"document_id": 42}).startswith("REFUSED")
        assert run_sources.refusal(mine, "read_vault_document", {"document_id": 41}) is None

    def test_the_funder_reader_opens_none_of_the_orgs_files(self):
        funder = readers.sources_for(proposal({"sources": [41]}), readers.FUNDER)
        assert run_sources.refusal(funder, "read_vault_document", {"document_id": 41}).startswith("REFUSED")


class TestWhatIsRead:
    def test_every_ticked_file_and_the_funder_at_first(self):
        assert readers.pending({"sources": [41, 42]}, NOW) == ["41", "42", "funder"]

    def test_try_again_reads_only_what_failed(self):
        work = {"sources": [41, 42], "readers": {"41": reader("done"), "42": reader("failed"), "funder": reader("done")}}
        assert readers.pending(work, NOW) == ["42"]

    def test_a_second_press_while_reading_is_refused(self):
        work = {"sources": [41], "readers": {"41": reader("running", minutes_ago=2)}}
        with pytest.raises(readers.Busy, match="Admin started reading the files 2 min ago"):
            readers.pending(work, NOW)

    def test_a_reader_running_past_the_longest_run_is_read_again(self):
        work = {"sources": [41], "readers": {"41": reader("running", minutes_ago=31), "funder": reader("done")}}
        assert readers.pending(work, NOW) == ["41"]

    def test_a_reread_keeps_a_confirmed_fact(self):
        held = fact_rules.make({"subject": "households surveyed", "value": "1,240", "origin": "vault",
                                "document_id": 41, "page": 12})
        work = {"facts": {"k1": {**held, "status": "confirmed"}}}
        again = fact_rules.make({"subject": "Households surveyed", "value": "1240", "origin": "vault",
                                 "document_id": 41, "page": 12})
        assert fact_rules.same_as(work, again) == "k1"

    def test_only_sangam_pitch_marks_a_reader(self):
        with pytest.raises(rules.BadChange):
            rules.apply({"sources": [41]}, {"readers.41": reader("done")}, by=ADMIN)
        assert rules.apply({"sources": [41]}, {"readers.41": reader("done")}, by=ADMIN, via="agent").work[
            "readers"]["41"]["status"] == "done"


STEP2 = {"skipped_template": True, "style": "plain"}


class TestLeavingStep2:
    def test_the_files_must_be_read_first(self):
        assert steps.exit_check(2, STEP2) == ["press Write the first draft"]

    def test_not_while_they_are_being_read(self):
        work = {**STEP2, "readers": {"41": {**reader("running"), "at": datetime.now(UTC).isoformat()}}}
        assert steps.exit_check(2, work) == ["wait until the files are read"]

    def test_a_failed_file_does_not_hold_it_up(self):
        assert steps.exit_check(2, {**STEP2, "readers": {"41": reader("failed"), "funder": reader("done")}}) == []

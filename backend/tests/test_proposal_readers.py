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

    build_proposal_agent(Settings(), InMemorySaver())
    return readers.BUILT


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

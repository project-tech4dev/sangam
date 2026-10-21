"""read_proposal's views and advance_step's outcomes, plus record_tools' registry and match text."""

from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace as NS
from uuid import UUID

import pytest

from app.core.security import CallerScope
from app.proposals import context
from app.proposals.tools import proposal_tools as pt
from app.proposals.tools import record_tools as rec
from app.repositories import profile_facts
from app.repositories import proposals as repo


class FakePool:
    def __init__(self, rows=()):
        self.rows, self.seen = list(rows), []

    @asynccontextmanager
    async def connection(self):
        yield self

    async def execute(self, sql, params=()):
        self.seen.append((sql, params))
        rows = self.rows

        class Cursor:
            async def fetchall(self):
                return rows

        return Cursor()


FACTS = {
    "k1": {"subject": "villages", "value": "96", "status": "confirmed", "origin": "registry", "section": "A2",
           "as_of": "2024-25", "source_name": "Registry"},
    "k2": {"subject": "old count", "value": "90", "status": "corrected", "origin": "registry", "section": "A2"},
    "k3": {"subject": "dropout", "value": "19.8%", "status": "proposed", "origin": "web", "section": "A3",
           "source_url": "https://udise.gov.in"},
}


def work(**kw):
    return {"stage": 3, "requirements": [{"key": "12a", "label": "12A registration", "hard": True}],
            "gates": {"12a": "yes"}, "skipped_template": True, "style": "plain, short",
            "sources": [41], "facts": dict(FACTS),
            "sections": {"A2": {"text": "Udalguri has 96 villages ⟦k1⟧.", "rev": 2, "score": 1, "needs_rewrite": True},
                         "A3": {"text": "done text", "done": True, "rev": 1}},
            "match": {"id": 5, "score": 72}, **kw}


def proposal(w=None, can_edit=True):
    return context.Current(id=1, title="t", org_id=7, org_name="SeSTA", funder_id=3, funder_name="ABF",
                           work=work() if w is None else w, scope=CallerScope(UUID(int=5), False, {7: "admin"}),
                           can_edit=can_edit)


@pytest.fixture
def opened(monkeypatch):
    def _open(p, rows=()):
        pool = FakePool(rows)

        async def current():
            return p

        monkeypatch.setattr(context, "current", current)
        for mod in (pt, rec):
            monkeypatch.setattr(mod, "get_pool", lambda: pool)
        return pool

    return _open


class TestReadProposal:
    async def test_the_outline_has_every_part(self, opened):
        pool = opened(proposal(), [{"id": 41, "title": "Annual report", "doc_type": "report", "as_of": "2024"}])
        out = await pt.read_proposal.ainvoke({})
        assert out.startswith("Step 3 of 5: Make a case")
        assert "- 12A registration (the funder needs it): yes" in out
        assert "Form: Sangam's usual order" in out
        assert "Documents Sangam may read: document 41 · Annual report · report · 2024" in out
        assert "Writing style: plain, short" in out
        assert "### Context and target area [A2] · draft · score 1 of 2 · NEEDS REWRITING" in out
        assert "### Problem and baseline [A3] · finished" in out
        assert "## This funder (funder)" in out
        assert pool.seen[0][1] == ([41], 7)

    async def test_one_part_alone(self, opened):
        pool = opened(proposal(work(sources=[], style="")))
        assert await pt.read_proposal.ainvoke({"part": "documents"}) == "Documents Sangam may read: none ticked"
        assert await pt.read_proposal.ainvoke({"part": "style"}) == "Writing style: not set"
        assert await pt.read_proposal.ainvoke({"part": "form"}) == "Form: Sangam's usual order"
        assert pool.seen == []  # no ticked file, no query

    async def test_a_ticked_file_without_title_or_date(self, opened):
        opened(proposal(), [{"id": 41, "title": None, "doc_type": None, "as_of": None}])
        assert await pt.read_proposal.ainvoke({"part": "documents"}) == \
            "Documents Sangam may read: document 41 · untitled · file"

    async def test_facts_lists_only_live_ones_with_their_ids(self, opened):
        opened(proposal())
        out = await pt.read_proposal.ainvoke({"part": "facts"})
        assert "- k1 · villages: 96 (2024-25) · confirmed, registry · Registry" in out
        assert "- k3 · dropout: 19.8% · proposed, web · https://udise.gov.in" in out
        assert "k2" not in out

    async def test_no_facts_yet(self, opened):
        opened(proposal(work(facts={})))
        assert await pt.read_proposal.ainvoke({"part": "facts"}) == "Every fact in use, cited by its id:\n- none yet"

    async def test_a_section_in_full_with_its_facts(self, opened):
        opened(proposal())
        out = await pt.read_proposal.ainvoke({"part": " A2 "})
        assert "Text (rev 2):\nUdalguri has 96 villages ⟦k1⟧." in out
        assert "A strong answer holds:" in out
        assert "- k1 · villages" in out and "k3" not in out

    async def test_an_empty_section_says_rev_zero(self, opened):
        opened(proposal())
        out = await pt.read_proposal.ainvoke({"part": "A5"})
        assert "No text yet (rev 0)." in out and "- none yet" in out

    async def test_a_tab_lists_its_sections_in_full(self, opened):
        opened(proposal())
        out = await pt.read_proposal.ainvoke({"part": "money"})
        assert out.startswith("## ") and "[A15]" in out and "[A2]" not in out

    async def test_an_unknown_part_is_explained(self, opened):
        opened(proposal())
        assert (await pt.read_proposal.ainvoke({"part": "Z9"})).startswith("No part 'Z9'. Use a tab (case")

    async def test_no_proposal_and_failure(self, monkeypatch):
        async def none():
            return None

        async def boom():
            raise KeyError("x")

        monkeypatch.setattr(context, "current", none)
        assert await pt.read_proposal.ainvoke({}) == pt.NO_PROPOSAL
        assert await pt.advance_step.ainvoke({}) == pt.NO_PROPOSAL
        monkeypatch.setattr(context, "current", boom)
        assert await pt.read_proposal.ainvoke({}) == "read_proposal failed: KeyError"
        assert await pt.advance_step.ainvoke({}) == "advance_step failed: KeyError"


class TestAdvanceStep:
    @pytest.fixture
    def saving(self, monkeypatch, opened):
        def _go(w, result="apply"):
            opened(proposal(w))

            async def save(pool, proposal_id, change):
                return None if result is None else change(w, "t")

            async def user_name(pool, user_id):
                return {"id": str(user_id), "name": "Asha"}

            monkeypatch.setattr(repo, "save", save)
            monkeypatch.setattr(repo, "user_name", user_name)

        return _go

    async def test_moves_on_when_nothing_is_missing(self, saving):
        saving(work())
        assert await pt.advance_step.ainvoke({}) == "Moved to step 4 of 5: Make a plan."

    async def test_says_what_is_missing(self, saving):
        saving(work(stage=1, gates={}))
        assert await pt.advance_step.ainvoke({}) == "NOT YET: to leave this step, answer 12A registration."

    async def test_a_reader_may_not_move_it(self, opened):
        opened(proposal(can_edit=False))
        assert await pt.advance_step.ainvoke({}) == pt.READ_ONLY

    async def test_a_proposal_gone_while_saving(self, saving):
        saving(work(), result=None)
        assert await pt.advance_step.ainvoke({}) == pt.NO_PROPOSAL


ORG = NS(id=7, name="SeSTA", legal_form="Society", district="Udalguri", state="Assam",
         registration_date=date(2010, 4, 1), staff_count=120, staff_count_note="full time",
         website="https://sesta.org", description="word " * 100,
         identifiers=[NS(id_type="12A", status="valid", valid_until="2027-03-31"),
                      NS(id_type="FCRA", status="lapsed", valid_until=None)])


def org_facts(**kw):
    base = {
        "org": ORG,
        "places": [NS(name="Udalguri", state="Assam"), NS(name="Assam", state=None)],
        "financials": [NS(fiscal_year="2024-25", total_income=2.4e7, program_spend=5e5, is_audited=True),
                    NS(fiscal_year="2023-24", total_income=None, program_spend=1e7, is_audited=False)],
        "programs": [NS(name="Wells", start_date="2019", end_date=None, description="Water",
                     metrics=[NS(name="wells dug", value=40, unit="wells", period="2024"),
                              NS(name="users", value=None, unit=None, period=None)]),
                  NS(name="Schools", start_date=None, end_date=None, description=None, metrics=[])],
        "funders": NS(groups=[NS(lines=[NS(funder_name="ABF", fiscal_year="2023-24", project_name=None,
                                        amount=3e6, id=41)])]),
    }
    return NS(**{**base, **kw})


class TestOrgText:
    def test_every_line_carries_its_marker(self):
        out = rec.org_text(org_facts())
        lines = out.splitlines()
        assert lines[0] == "SeSTA [org:7] · Society · Udalguri · Assam"
        assert "Registered 2010-04-01 [org:7]" in lines
        assert "Staff: 120 (full time) [org:7]" in lines
        assert "Registrations: 12A valid until 2027-03-31; FCRA lapsed [org:7]" in lines
        assert "Works in: Udalguri, Assam; Assam [org:7]" in lines
        assert "FY 2024-25: income ₹2.40 crore, programmes ₹5.00 lakh, audited [org:7]" in lines
        assert "FY 2023-24: income not public, programmes ₹1.00 crore [org:7]" in lines
        assert "Programme: Wells (2019 to now). Water [org:7]" in lines
        assert "  - wells dug: 40 wells (2024) [org:7]" in lines
        assert "  - users: ?  [org:7]" in lines
        assert "Programme: Schools.  [org:7]" in lines
        assert "Funded by ABF, FY 2023-24: a grant, ₹30.00 lakh [activity:41]" in lines
        about = next(line for line in lines if line.startswith("About:"))
        assert "…" in about and len(about) < rec.TEXT + 30

    def test_a_bare_record_is_one_line(self):
        bare = NS(**{**vars(ORG), "legal_form": None, "district": None, "state": None, "registration_date": None,
                     "staff_count": 0, "website": None, "description": None, "identifiers": []})
        out = rec.org_text(org_facts(org=bare, places=[], financials=[], programs=[], funders=NS(groups=[])))
        assert out == "SeSTA [org:7]"


MATCH = {"id": 5, "run_at": "2026-10-01T10:00:00", "detail": {
    "summary": "A good fit.",
    "criteria": [{"label": "Theme", "points": 25, "max": 25, "status": "met", "note": "Water.", "cites": ["[org:7]"]},
                 {"label": "Size", "points": None, "max": 10, "status": "unknown"}],
    "not_judged": ["capacity"], "improve": ["file FCRA"]}}


class TestMatch:
    def test_match_text(self):
        lines = rec.match_text(MATCH).splitlines()
        assert lines[0] == "Funder Match [score:5], saved 2026-10-01: A good fit."
        assert lines[1] == "- Theme: 25 of 25, met. Water. [org:7]"
        assert lines[2].startswith("- Size: not judged, unknown.")
        assert lines[3:] == ["Not judged:", "- capacity", "What would raise the score:", "- file FCRA"]

    async def test_read_match_reads_the_saved_run(self, opened, monkeypatch):
        opened(proposal())

        async def match_for(pool, org_id, funder_id):
            assert (org_id, funder_id) == (7, 3)
            return MATCH

        monkeypatch.setattr(repo, "match_for", match_for)
        assert (await rec.read_match.ainvoke({})).startswith("Funder Match [score:5]")

    @pytest.mark.parametrize("held, note", [
        (None, ""), ({**MATCH, "id": 6}, " A newer run exists; this proposal keeps the one it started from.")])
    async def test_a_missing_or_newer_run_keeps_the_proposals_own(self, opened, monkeypatch, held, note):
        opened(proposal())

        async def match_for(pool, org_id, funder_id):
            return held

        monkeypatch.setattr(repo, "match_for", match_for)
        assert await rec.read_match.ainvoke({}) == f"The saved match [score:5] scored 72/100.{note}"

    async def test_read_org_record(self, opened, monkeypatch):
        opened(proposal())
        held = {"facts": org_facts()}

        async def facts(pool, owner, org_id):
            assert org_id == "7"
            return held["facts"]

        monkeypatch.setattr(profile_facts, "org_facts", facts)
        assert (await rec.read_org_record.ainvoke({})).startswith("SeSTA [org:7]")
        held["facts"] = None
        assert await rec.read_org_record.ainvoke({}) == "Sangam holds no record for SeSTA."

    @pytest.mark.parametrize("tool", [rec.read_match, rec.read_org_record])
    async def test_no_proposal_and_failure(self, monkeypatch, tool):
        async def none():
            return None

        async def boom():
            raise ValueError

        monkeypatch.setattr(context, "current", none)
        assert await tool.ainvoke({}) == "No proposal is open in this chat."
        monkeypatch.setattr(context, "current", boom)
        assert await tool.ainvoke({}) == f"{tool.name} failed: ValueError"

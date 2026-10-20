"""write_section's refusals and its saved message, with the grader and the district list faked."""

from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from langgraph.errors import GraphInterrupt

from app.core.security import CallerScope
from app.proposals import context, grade, records, rubric
from app.proposals.tools import writing_tools as wt
from app.repositories import proposals as repo

FACTS = {"k4": {"subject": "villages", "value": "96 villages", "evidence": "96 villages in Baksa",
                "status": "proposed"},
         "k5": {"subject": "spend", "value": "Rs 1.12 crore", "status": "confirmed"}}


def proposal(stage=3, sections=None, can_edit=True):
    w = {"stage": stage, "facts": FACTS, "sections": sections or {}}
    return context.Current(id=1, title="t", org_id=7, org_name="AJAGAR", funder_id=3, funder_name="APF", work=w,
                           scope=CallerScope(UUID(int=5), False, {7: "steward"}), can_edit=can_edit)


@pytest.fixture
def opened(monkeypatch):
    store = {}

    def _open(p, *, graded=None, saved=True):
        store.update(work=p.work, saves=0)

        async def current():
            return p

        async def save(pool, proposal_id, change):
            store["saves"] += 1
            if not saved:
                return None
            store["work"] = change(store["work"], "t").work
            return store["work"]

        async def districts(pool):
            return {"baksa"}

        async def user_name(pool, user_id):
            return {"id": str(UUID(int=5)), "name": "Asha"}

        async def grader(section, text, model):
            return graded

        monkeypatch.setattr(context, "current", current)
        monkeypatch.setattr(wt, "get_pool", lambda: None)
        monkeypatch.setattr(wt, "resolve_model", lambda name: None)
        monkeypatch.setattr(records, "districts", districts)
        monkeypatch.setattr(repo, "user_name", user_name)
        monkeypatch.setattr(repo, "save", save)
        monkeypatch.setattr(grade, "grade", grader)
        return store

    return _open


async def write(code="A2", text="AJAGAR works in 96 villages of Baksa ⟦k4⟧.", rev=0, part=None):
    state = {"ag-ui": {"context": [{"description": context.SCREEN, "value": {"part": part}}]}} if part else {}
    return await wt.write_section.coroutine(code=code, text=text, rev=rev, runtime=NS(state=state, tool_call_id="c"))


class TestWriteSection:
    async def test_a_traced_section_is_saved_and_graded(self, opened):
        strong = list(next(s for s in rubric.sections_for(False) if s.code == "A2").strong)
        store = opened(proposal(), graded=grade.Graded(covered=strong[1:], missing=strong[:1]))
        out = await write()
        assert out == (f"SAVED Context and target area [A2]. Score 1 of 2. A strong answer still needs: {strong[0]}.")
        part = store["work"]["sections"]["A2"]
        assert part["rev"] == 1 and part["missing"] == strong[:1]
        assert store["work"]["facts"]["k4"]["used_in"] == ["A2"]

    async def test_an_untraced_number_is_refused_with_each_claim(self, opened):
        store = opened(proposal())
        out = await write(text="It reached 120 villages and 300 schools.")
        assert out.startswith("REFUSED: Context and target area [A2] was not saved. ")
        assert "120" in out and store["saves"] == 0

    async def test_more_than_eight_problems_are_counted_not_listed(self, opened):
        opened(proposal())
        text = "\n\n".join(f"It reached {n}1 villages." for n in range(1, 12))
        assert "and 3 more." in await write(text=text)

    @pytest.mark.parametrize("code, text, out", [
        ("Z9", "x", "REFUSED: this proposal has no section 'Z9'."),
        ("A2", "   ", f"REFUSED: a section's text is 1 to {wt.TEXT_LIMIT:,} characters."),
        ("A2", "x" * (wt.TEXT_LIMIT + 1), f"REFUSED: a section's text is 1 to {wt.TEXT_LIMIT:,} characters."),
    ])
    async def test_bad_input_is_refused(self, opened, code, text, out):
        opened(proposal())
        assert await write(code=code, text=text) == out

    async def test_objectives_wait_for_the_problem_unless_on_screen(self, opened):
        opened(proposal())
        assert (await write(code="A4", text="Halve the dropout.")).startswith("NOT YET: write ")
        assert (await write(code="A4", text="Halve the dropout.", part="A4")).startswith("SAVED Objectives")

    async def test_step_two_and_a_reader_are_refused(self, opened):
        opened(proposal(stage=2))
        assert (await write()).startswith("REFUSED: write_section is used from step 3")
        opened(proposal(can_edit=False))
        assert (await write()).startswith("REFUSED: you can read")

    async def test_a_teammates_newer_text_is_not_overwritten(self, opened):
        opened(proposal(sections={"A2": {"text": "Ravi's", "rev": 2, "by": {"name": "Ravi"}}}))
        out = await write(rev=1)
        assert out.startswith("REFUSED: ") and "(now rev 2)" in out

    async def test_a_proposal_gone_while_saving(self, opened):
        opened(proposal(), saved=False)
        assert await write() == wt.NO_PROPOSAL

    async def test_no_proposal_and_failure(self, monkeypatch):
        async def none():
            return None

        async def boom():
            raise LookupError

        monkeypatch.setattr(context, "current", none)
        assert await write() == wt.NO_PROPOSAL
        monkeypatch.setattr(context, "current", boom)
        assert await write() == "write_section failed: LookupError"


class TestSuggestEditEdges:
    async def call(self, now="96 villages of Baksa ⟦k4⟧", better="96 Baksa villages ⟦k4⟧"):
        return await wt.suggest_edit.coroutine(code="A2", now=now, better=better, why="w",
                                               runtime=NS(state={}, tool_call_id="c"))

    async def test_an_unwritten_part_and_a_reader(self, opened):
        opened(proposal())
        assert (await self.call()).startswith("REFUSED: 'A2' is not a written section")
        opened(proposal(can_edit=False))
        assert (await self.call()).startswith("REFUSED: you can read")

    async def test_a_swap_past_the_limit(self, opened):
        opened(proposal(sections={"A2": {"text": "AJAGAR works in 96 villages of Baksa ⟦k4⟧.", "rev": 1}}))
        assert await self.call(better="x" * wt.TEXT_LIMIT) == \
            f"REFUSED: a section's text is at most {wt.TEXT_LIMIT:,} characters."

    async def test_the_pause_and_a_failure(self, opened, monkeypatch):
        opened(proposal(sections={"A2": {"text": "AJAGAR works in 96 villages of Baksa ⟦k4⟧.", "rev": 1}}))

        def interrupt(card):
            raise GraphInterrupt(())

        monkeypatch.setattr(wt, "interrupt", interrupt)
        with pytest.raises(GraphInterrupt):
            await self.call()

        async def none():
            return None

        async def boom():
            raise LookupError

        monkeypatch.setattr(context, "current", none)
        assert await self.call() == wt.NO_PROPOSAL
        monkeypatch.setattr(context, "current", boom)
        assert await self.call() == "suggest_edit failed: LookupError"


def _section(code, strong=("a", "b")):
    return rubric.Section(**{**vars(next(s for s in rubric.sections_for(False) if s.code == code)),
                             "strong": tuple(strong)})


class TestSavedMessage:
    def test_ungraded_without_a_rubric_or_after_a_failed_grader(self):
        assert wt._saved(_section("A2", ()), "x", None).endswith("it has no strong answer to grade against.")
        assert wt._saved(_section("A2"), "x", None).endswith("it can be graded on the next save.")

    def test_a_must_score_two_part_below_two_is_sent_back(self):
        out = wt._saved(_section("A15"), "x [Add: unit costs] [Add: totals]", grade.Graded(missing=["a"]))
        assert "Budget must score 2" in out and out.endswith("2 gaps marked [Add: …]: ask about them one at a time.")

    def test_full_marks_and_one_gap(self):
        out = wt._saved(_section("A2"), "x [Add: y]", grade.Graded(missing=[]))
        assert out == "SAVED Context and target area [A2]. Score 2 of 2. 1 gap marked [Add: …]: ask about them one at a time."

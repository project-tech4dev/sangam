"""Suggested wording's code-only safeguards: an exact passage, traced claims, and nothing saved unless used."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.security import CallerScope
from app.proposals import context, grade, records
from app.proposals import work as work_rules
from app.proposals.tools import writing_tools
from app.repositories import proposals as repo

ORG = 7
TEXT = "AJAGAR works in 96 villages of Baksa ⟦k4⟧. It has done good work.\n\nIt spent ₹1.12 crore ⟦k5⟧."
FACTS = {"k4": {"subject": "villages", "value": "96 villages", "evidence": "96 villages in Baksa", "status": "proposed"},
         "k5": {"subject": "CSR spend", "value": "Rs 1.12 crore", "status": "confirmed"}}


def current(stage=3):
    work = {"stage": stage, "facts": FACTS, "sections": {"A2": {"text": TEXT, "rev": 2}}}
    return context.Current(id=1, title="AJAGAR to APF", org_id=ORG, org_name="AJAGAR", funder_id=3,
                           funder_name="Azim Premji Foundation", work=work,
                           scope=CallerScope(UUID(int=5), False, {ORG: "steward"}), can_edit=True)


@pytest.fixture
def run(monkeypatch):
    """Calls suggest_edit with the person's reply already given; returns what it said and the saved work."""
    saved = {}

    async def save(pool, proposal_id, change):
        saved["work"] = change(saved.get("base", current().work), "AJAGAR to APF").work
        return saved["work"]

    async def none(*args, **kwargs):
        return None

    async def districts(pool):
        return {"baksa", "udalguri"}

    async def user_name(pool, user_id):
        return {"id": str(UUID(int=5)), "name": "Asha"}

    monkeypatch.setattr(writing_tools, "get_pool", lambda: None)
    monkeypatch.setattr(records, "districts", districts)
    monkeypatch.setattr(repo, "user_name", user_name)
    monkeypatch.setattr(repo, "save", save)
    monkeypatch.setattr(grade, "grade", none)

    async def call(now, better, reply=None, stage=3, base=None):
        shown = []

        async def proposal():
            return current(stage)

        def interrupt(card):
            shown.append(card)
            return reply

        if base is not None:
            saved["base"] = base
        monkeypatch.setattr(context, "current", proposal)
        monkeypatch.setattr(writing_tools, "interrupt", interrupt)
        out = await writing_tools.suggest_edit.coroutine(
            code="A2", now=now, better=better, why="names the work",
            runtime=SimpleNamespace(tool_call_id="c1", state={}))
        return out, shown, saved.get("work")

    return call


class TestThePassage:
    def test_it_must_appear_exactly_once(self):
        assert writing_tools.swap(TEXT, "It has done good work.", "It runs gardens.") is not None
        assert writing_tools.swap(TEXT, "not in the text", "x") is None
        assert writing_tools.swap(TEXT, "It ", "x") is None

    def test_marks_outside_the_passage_stay(self):
        out = writing_tools.swap(TEXT, "It has done good work.", "It runs kitchen gardens.")
        assert "⟦k4⟧" in out and "⟦k5⟧" in out and "kitchen gardens" in out


class TestTheCard:
    async def test_untraced_wording_is_refused_before_the_person_sees_it(self, run):
        out, shown, saved = await run("It has done good work.", "It has reached 120 villages.", {"kind": "pick"})
        assert out.startswith("REFUSED") and "120" in out and shown == [] and saved is None

    async def test_a_problem_already_in_the_text_does_not_block_a_suggestion(self, run):
        out, shown, _ = await run("It has done good work.", "It runs kitchen gardens.", {"kind": "pick", "choice": "keep"})
        assert shown and shown[0]["now"] == "It has done good work." and out.startswith("KEPT")

    async def test_kept_saves_nothing(self, run):
        out, _, saved = await run("It has done good work.", "It runs kitchen gardens.", {"kind": "pick", "choice": "keep"})
        assert out.startswith("KEPT") and saved is None

    async def test_used_saves_the_new_text_as_the_next_rev(self, run):
        out, shown, saved = await run("works in 96 villages of Baksa ⟦k4⟧", "reaches 96 villages in Baksa ⟦k4⟧",
                                      {"kind": "pick", "choice": "use"})
        assert shown[0]["better"] == "reaches 96 villages in Baksa"
        assert out.startswith("SAVED") and saved["sections"]["A2"]["rev"] == 3
        assert "reaches 96 villages in Baksa ⟦k4⟧" in saved["sections"]["A2"]["text"]

    async def test_a_typed_reply_comes_back_as_feedback(self, run):
        out, _, saved = await run("It has done good work.", "It runs gardens.", {"kind": "text", "text": "shorter"})
        assert out.startswith("FEEDBACK") and "shorter" in out and saved is None

    async def test_used_after_a_teammate_changed_the_part_is_refused(self, run):
        newer = current().work | {"sections": {"A2": {"text": TEXT + " More.", "rev": 3,
                                                      "by": {"name": "Ravi"}}}}
        out, _, _ = await run("It has done good work.", "It runs gardens.", {"kind": "pick", "choice": "use"}, base=newer)
        assert out.startswith("REFUSED") and "since you read it" in out

    async def test_it_waits_for_step_three(self, run):
        out, shown, _ = await run("It has done good work.", "It runs gardens.", stage=2)
        assert out.startswith("REFUSED") and "step 3" in out and shown == []


def test_only_code_may_save_through_it():
    with pytest.raises(work_rules.BadChange):
        work_rules.apply({}, {"sections.A2.score": 2}, {"A2": 0}, by={"id": None, "name": "Asha"})

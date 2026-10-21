"""Make a case: its step rules, and secondary research's one traced paragraph per topic."""

from datetime import UTC, datetime

import pytest

from app.proposals import questions, research, rubric, steps
from app.proposals import work as work_rules

NOW = datetime(2026, 10, 21, tzinfo=UTC).isoformat()


def fact(subject, value, topic=None, *, section="A3", status="proposed", found_by="public", **extra):
    return {"subject": subject, "value": value, "section": section, "status": status, "found_by": found_by,
            "origin": "web", **({"topic": topic} if topic else {}), **extra}


FACTS = {
    "k1": fact("secondary dropout, Udalguri", "19.8%", "problem", as_of="2023-24", source_name="UDISE+ 2023-24"),
    "k2": fact("secondary dropout, Assam", "15.1%", "problem", as_of="2023-24"),
    "k3": fact("Aspirational District", "Udalguri is one", "place", section="A2"),
    "k4": fact("set aside", "40%", "problem", status="rejected"),
    "k5": fact("from a file", "12%", "problem", found_by=None),
}


class TestSteps:
    def test_there_are_five_steps_and_make_a_case_is_third(self):
        assert steps.STAGES[3] == "Make a case" and steps.STAGES[4] == "Make a plan" and steps.LAST == 5

    def test_make_a_case_is_left_once_context_and_problem_are_written(self):
        assert steps.exit_check(3, {}) == ["write Context and target area", "write Problem and baseline"]
        assert steps.exit_check(3, {"sections": {"A2": {"text": "x"}, "A3": {"text": " "}}}) == \
            ["write Problem and baseline"]
        assert steps.exit_check(3, {"sections": {"A2": {"text": "x"}, "A3": {"text": "y"}}}) == []

    def test_a_click_forward_passes_every_step_on_the_way(self):
        written = {"A2": {"text": "x"}, "A3": {"text": "y"}}
        assert steps.furthest({"stage": 3}) == 3
        assert steps.furthest({"stage": 3, "sections": written}) == 5
        assert steps.blocking({"stage": 3}, 5) == ["write Context and target area", "write Problem and baseline"]
        assert steps.blocking({"stage": 3, "sections": written}, 5) == []
        assert steps.blocking({"stage": 5}, 5) == []

    def test_make_a_plan_has_no_gate_and_the_last_step_is_last(self):
        assert steps.exit_check(4, {}) == [] and steps.exit_check(5, {}) == ["this is the last step"]

    def test_the_case_is_step_three_and_the_rest_step_four(self):
        by_code = {s.code: s.out() for s in rubric.CORE}
        assert [c for c, s in by_code.items() if s["step"] == 3] == ["A1", "A2", "A3"]
        assert {by_code[c]["tab"] for c in ("A4", "A5", "A6", "A7")} == {"plan"}
        assert dict(rubric.TABS)["plan"] == "Objectives and plan"

    def test_questions_on_either_writing_step_are_about_the_part_on_screen(self):
        q = {"section": "A4", "reason": "missing", "element": "Objectives stated as changes"}
        for stage in (3, 4):
            assert questions.may_ask({"stage": stage}, q, me="u", on_screen="A3")[0] == \
                "ask only about the part the person has open on screen"
        assert questions.may_ask({"stage": 5}, q, me="u", on_screen="A3")[0] is None


class TestTopics:
    def test_a_fact_without_a_topic_falls_back_to_its_section(self):
        assert research.topic_of({"section": "A2"}) == "place"
        assert research.topic_of({"section": "F1", "subject": "SDG 4.1"}) == "sdg"
        assert research.topic_of({"section": "F1", "subject": "Samagra Shiksha"}) == "government"
        assert research.topic_of({"section": "B9"}) == "problem"

class TestAsks:
    ASK = {"kind": "chat", "ask": "SHG credit", "focus": ["SHG credit linkage"], "sites": [], "sections": [],
           "status": "running", "at": NOW}

    def test_an_ask_is_checked_before_it_is_kept(self):
        assert research.bad_ask(self.ASK) is None
        assert "kind" in research.bad_ask({**self.ASK, "kind": "other"})
        assert "running" in research.bad_ask({**self.ASK, "status": "queued"})
        assert "500" in research.bad_ask({**self.ASK, "ask": "x" * 501})
        assert "lists" in research.bad_ask({**self.ASK, "focus": ["x"] * 9})

    def test_only_sangam_pitch_records_an_ask(self):
        from app.proposals import work as rules

        by = {"id": "u", "name": "Ravi"}
        with pytest.raises(rules.BadChange, match="asked for in the chat"):
            rules.apply({"stage": 3}, {"research_asks.a1": self.ASK}, by=by)
        assert rules.apply({"stage": 3}, {"research_asks.a1": self.ASK}, by=by, via="agent").work[
            "research_asks"]["a1"]["ask"] == "SHG credit"
        assert research.next_ask_id({"research_asks": {"a1": {}, "a7": {}}}) == "a8"

    def test_an_angle_naming_the_org_or_a_partner_is_left_out(self):
        kept, dropped = research.focus(["  SHG credit   linkage, Assam ", "KABIL federations", "", "Seva Mandir work"],
                                       {"kabil", "seva mandir"})
        assert kept == ["SHG credit linkage, Assam"] and dropped == ["KABIL federations", "Seva Mandir work"]

    def test_a_site_is_kept_as_its_host(self):
        assert research.sites(["https://NRLM.gov.in/outer/x?y", "nrlm.gov.in", "rchiips.org", "not a site", ""]) == \
            ["nrlm.gov.in", "rchiips.org"]

    def test_only_public_facts_still_in_use_are_named_as_found(self):
        assert research.already_found({"facts": FACTS}) == [
            "secondary dropout, Udalguri: 19.8%", "secondary dropout, Assam: 15.1%", "Aspirational District: Udalguri is one"]


class TestReset:
    PUB = {"found_by": "public", "status": "proposed"}

    def test_it_removes_public_facts_nothing_relies_on(self):
        work = {"facts": {"k1": self.PUB, "k2": self.PUB, "k3": self.PUB, "k4": {**self.PUB, "found_by": None},
                          "k5": {"from": ["k2"]}, "k6": {"supersedes": "k3"}, "k7": self.PUB},
                "sections": {"A2": {"text": "Udalguri ⟦k1⟧."}, "A3": None},
                "readers": {"public": {"status": "done"}}, "research_asks": {"a1": {}}}
        assert research.reset(work) == {"facts.k7": None, "readers.public": None, "research_asks": None}

    def test_nothing_to_reset(self):
        assert research.reset({"facts": {"k1": {"found_by": None}}, "readers": {"funder": {}}}) == {}

    def test_only_reset_may_remove_and_only_public_facts(self):
        work = {"facts": {"k1": self.PUB, "k2": {"found_by": None}}}
        out = work_rules.apply(work, {"facts.k1": None}, by={"id": "u"}, via=work_rules.RESET)
        assert "k1" not in out.work["facts"]
        with pytest.raises(work_rules.BadChange):
            work_rules.apply(work, {"facts.k2": None}, by={"id": "u"}, via=work_rules.RESET)
        with pytest.raises(work_rules.BadChange):
            work_rules.apply(work, {"research_asks": None}, by={"id": "u"}, via="rest")


class TestDeeper:
    CASE = {"sections": {"A1": {"text": "KABIL works in Mazbat ⟦k1⟧."},
                         "A2": {"text": "Mazbat Block, Udalguri ⟦k2⟧. [Add: population by group]", "done": True},
                         "A3": {"text": "", "done": False}}}

    def test_it_waits_for_context_and_problem_but_not_the_summary(self):
        assert research.not_ready(self.CASE) == ["mark Problem and baseline done"]
        assert research.not_ready({"sections": {"A2": {"done": True}, "A3": {"done": True}}}) == []

    def test_the_case_is_read_without_its_fact_ids(self):
        text = research.case_text(self.CASE)
        assert text == ("## Summary\nKABIL works in Mazbat.\n\n"
                        "## Context and target area\nMazbat Block, Udalguri. [Add: population by group]")

    async def test_angles_naming_the_org_are_dropped(self):
        class Angles:
            def with_structured_output(self, schema):
                class Bound:
                    async def ainvoke(self, messages):
                        Bound.asked = messages[1].content
                        return schema(angles=["population by social group, Udalguri", "KABIL members"])

                return Bound()

        kept, dropped = await research.angles(self.CASE, Angles(), {"kabil"})
        assert kept == ["population by social group, Udalguri"] and dropped == ["KABIL members"]

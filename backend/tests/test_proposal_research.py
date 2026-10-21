"""Make a case: its step rules, and secondary research's one traced paragraph per topic."""

from datetime import UTC, datetime

from app.proposals import questions, research, rubric, steps

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


class Model:
    """A structured-output model answering each topic from `replies`, or raising."""

    def __init__(self, replies):
        self.replies, self.asked = replies, []

    def with_structured_output(self, schema):
        model = self

        class Bound:
            async def ainvoke(self, messages):
                ask = messages[1].content
                model.asked.append(ask)
                topic = next(t for t, label in research.LABELS.items() if f"Topic: {label}" in ask)
                reply = model.replies[topic]
                if isinstance(reply, Exception):
                    raise reply
                return schema(text=reply)

        return Bound()


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

    def test_only_live_secondary_research_facts_count(self):
        assert list(research.found({"facts": FACTS}, "problem")) == ["k1", "k2"]


class TestChecked:
    facts = {k: FACTS[k] for k in ("k1", "k2")}

    def test_a_traced_paragraph_is_kept_on_one_line(self):
        text = "Dropout is 19.8% in Udalguri ⟦k1⟧,\n\nagainst 15.1% in Assam ⟦k2⟧."
        assert research.checked(text, self.facts) == "Dropout is 19.8% in Udalguri ⟦k1⟧, against 15.1% in Assam ⟦k2⟧."

    def test_a_figure_no_cited_fact_holds_is_refused(self):
        assert research.checked("Dropout is 25% in Udalguri ⟦k1⟧.", self.facts) is None

    def test_no_citation_another_topics_fact_or_too_long_is_refused(self):
        assert research.checked("Dropout is high.", self.facts) is None
        assert research.checked("Udalguri is an Aspirational District ⟦k3⟧.", self.facts) is None
        assert research.checked("x ⟦k1⟧ " * 400, self.facts) is None


class TestSummarise:
    async def test_each_topic_with_facts_gets_its_traced_paragraph(self):
        model = Model({"problem": "Dropout is 19.8% in Udalguri ⟦k1⟧.", "place": "It is an Aspirational District ⟦k3⟧."})
        out = await research.summarise({"facts": FACTS}, model)
        assert out == {"problem": "Dropout is 19.8% in Udalguri ⟦k1⟧.", "place": "It is an Aspirational District ⟦k3⟧."}
        problem = next(a for a in model.asked if "The problem, measured" in a)
        assert "- k1 · secondary dropout, Udalguri: 19.8% (2023-24) · UDISE+ 2023-24" in problem
        assert "set aside" not in problem and "from a file" not in problem

    async def test_a_failed_call_or_an_untraced_paragraph_leaves_the_topic_out(self):
        model = Model({"problem": RuntimeError("down"), "place": "It is one of 112 districts ⟦k3⟧."})
        assert await research.summarise({"facts": FACTS}, model) == {}

    async def test_no_facts_no_call(self):
        model = Model({})
        assert await research.summarise({}, model) == {} and model.asked == []

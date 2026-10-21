"""Writing's code-only safeguards: the trace check, the order sections are written in, and who may score them."""

from uuid import UUID

import pytest

from app.proposals import grade, rubric, steps, trace
from app.proposals import work as rules

ADMIN = {"id": str(UUID(int=5)), "name": "Admin"}
FACTS = {
    "k4": {"subject": "villages reached", "value": "96 villages", "evidence": "96 villages in Udalguri and Baksa, Assam",
           "status": "proposed"},
    "k5": {"subject": "CSR spend", "value": "Rs 1.12 crore", "status": "confirmed"},
    "k6": {"subject": "food secure", "value": "38%", "status": "rejected"},
    "k7": {"subject": "budget", "value": "₹1,12,00,000", "status": "proposed"},
    "k8": {"subject": "partner", "value": "Tata Trusts", "kind": "name", "status": "proposed"},
}
DISTRICTS = {"baksa", "udalguri", "kamrup"}


def problems(text):
    return trace.check(text, FACTS, districts=DISTRICTS, names={"tata trusts"})


class TestTheTraceCheck:
    def test_a_traced_paragraph_passes(self):
        assert problems("AJAGAR works in 96 villages of Baksa, Assam ⟦k4⟧. It spent ₹1.12 crore ⟦k5⟧.") == []

    def test_a_number_its_facts_do_not_hold_is_refused(self):
        assert problems("It works in 60 villages in Baksa ⟦k4⟧.") == ["paragraph 1: 60 is in no fact it cites"]

    def test_lakh_and_crore_are_the_same_rupees(self):
        assert problems("It spent ₹112 lakh ⟦k7⟧.") == []
        assert problems("It spent ₹1.12 crore ⟦k7⟧.") == []

    def test_a_place_needs_a_fact_that_names_it(self):
        assert problems("It will expand to Kamrup ⟦k4⟧.") == ["paragraph 1: Kamrup is in no fact it cites"]

    def test_a_partner_needs_its_fact_cited(self):
        assert problems("With Tata Trusts it reached 96 villages ⟦k4⟧.") == [
            "paragraph 1: Tata Trusts is in no fact it cites"]
        assert problems("With Tata Trusts ⟦k8⟧ it reached 96 villages ⟦k4⟧.") == []

    def test_a_citation_counts_only_in_its_own_paragraph(self):
        assert problems("It reached 96 villages ⟦k4⟧.\n\nThose 96 villages are poor.") == [
            "paragraph 2: 96 is in no fact it cites"]

    def test_years_fy_and_schedule_vii_need_no_fact(self):
        assert problems("In FY2024-25, between 2019–22 and in 2026, under Schedule VII (i), it reached 96 villages ⟦k4⟧.") == []

    def test_a_gap_is_not_a_claim(self):
        assert problems("Food security was [Add: % of households food-secure in 2025].") == []

    def test_a_set_aside_or_unknown_fact_cannot_be_cited(self):
        assert "set aside" in problems("Only 38% are food secure ⟦k6⟧.")[0]
        assert "does not hold" in problems("See ⟦k99⟧.")[0]


class TestTheOrder:
    def test_objectives_wait_for_context_and_problem(self):
        assert "Context and target area [A2], Problem and baseline [A3] first" in steps.may_write({}, "A4", None)

    def test_the_part_on_screen_is_the_persons_pick(self):
        assert steps.may_write({}, "A4", "A4") is None

    def test_the_summary_is_written_last(self):
        written = {s.code: {"text": "x"} for s in rubric.CORE if s.code not in ("A1", "A14")}
        assert "Sustainability and exit [A14]" in steps.may_write({"sections": written}, "A1", None)

    def test_the_summary_waits_even_when_it_is_on_screen(self):
        assert "Context and target area [A2]" in steps.may_write({}, "A1", "A1")


class TestScoring:
    def test_none_missing_scores_two_one_scores_one_more_scores_zero(self):
        assert [rubric.score([]), rubric.score(["a"]), rubric.score(["a", "b"])] == [2, 1, 0]

    def test_only_sangam_pitch_scores_a_section_or_marks_where_a_fact_is_used(self):
        with pytest.raises(rules.BadChange):
            rules.apply({}, {"sections.A3.score": 2}, {"A3": 0}, by=ADMIN)
        with pytest.raises(rules.BadChange):
            rules.apply({"facts": {"k4": FACTS["k4"]}}, {"facts.k4.used_in": ["A3"]}, by=ADMIN)
        out = rules.apply({}, {"sections.A3.text": "t", "sections.A3.score": 1}, {"A3": 0}, by=ADMIN, via="agent")
        assert out.work["sections"]["A3"] == {"text": "t", "score": 1, "rev": 1}

    async def test_the_grade_keeps_only_the_rubrics_own_elements(self):
        a3 = next(s for s in rubric.CORE if s.code == "A3")

        class Model:
            def with_structured_output(self, _):
                return self

            async def ainvoke(self, _):
                return grade.Graded(covered=[], missing=["The causes the project will act on", "invented"])

        graded = await grade.grade(a3, "text", Model())
        assert graded.missing == ["The causes the project will act on"]


class TestWritingInPlace:
    def test_an_unsourced_claim_is_listed_as_written(self):
        text = ("In FY2024-25 it reached 120 villages in Kamrup ⟦k4⟧ and spent ₹1.5 crore.\n\n"
                "It reached 96 villages ⟦k4⟧.")
        assert trace.unsourced(text, FACTS, districts=DISTRICTS) == ["120", "₹1.5 crore", "Kamrup"]

    def test_a_typed_part_tracks_its_facts_clears_done_and_stops_ready(self):
        work = {"facts": {"k4": dict(FACTS["k4"], used_in=["A2"])},
                "sections": {"A2": {"text": "96 villages ⟦k4⟧", "done": True, "rev": 2, "score": 2,
                                    "missing": []}}}
        out = rules.apply(work, {"sections.A2.text": "It works in 120 villages."}, {"A2": 2}, by=ADMIN,
                          districts=DISTRICTS)
        part = out.work["sections"]["A2"]
        assert (part["done"], part["untraced"], part["rev"]) == (False, ["120"], 3)
        assert (part["score"], part["missing"]) == (None, None)
        assert out.work["facts"]["k4"]["used_in"] == []
        assert "Context and target area: “120” has no source" in out.summary["fix_first"]

    def test_citing_it_clears_the_list(self):
        work = {"facts": {"k4": FACTS["k4"]},
                "sections": {"A2": {"text": "120 villages", "untraced": ["120"], "rev": 1}}}
        out = rules.apply(work, {"sections.A2.text": "96 villages ⟦k4⟧"}, {"A2": 1}, by=ADMIN)
        assert out.work["sections"]["A2"]["untraced"] == []
        assert out.work["facts"]["k4"]["used_in"] == ["A2"]

    @pytest.mark.parametrize("via", ["rest", "agent"])
    def test_what_a_part_misses_or_cannot_trace_is_never_set_from_outside(self, via):
        for field in ("missing", "untraced"):
            with pytest.raises(rules.BadChange):
                rules.apply({}, {f"sections.A3.{field}": []}, {"A3": 0}, by=ADMIN, via=via)

    def test_done_stores_the_grade(self):
        work = {"sections": {"A3": {"text": "t", "rev": 1}}}
        out = rules.apply(work, {"sections.A3.done": True}, {"A3": 1}, by=ADMIN,
                          graded={"A3": ["The causes the project will act on"]})
        assert out.work["sections"]["A3"] == {"text": "t", "done": True, "score": 1, "rev": 2,
                                              "missing": ["The causes the project will act on"]}

    async def test_the_route_grades_only_parts_marked_done(self, monkeypatch):
        from app.api.routes import proposals as route

        seen = []

        async def graded(section, text, model):
            seen.append((section.code, text))
            return grade.Graded(covered=[], missing=[])

        monkeypatch.setattr(grade, "grade", graded)
        monkeypatch.setattr("app.agent.models.resolve_model", lambda name: None)
        work = {"sections": {"A3": {"text": "held"}, "A4": {"text": "x"}}}
        out = await route._grade_done(work, {"sections.A3.done": True, "sections.A4.done": False,
                                             "sections.A2.done": True}, {"A3": 0, "A4": 0, "A2": 0})
        assert out == {"A3": []} and seen == [("A3", "held")]

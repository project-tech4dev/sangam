"""Review's code-only safeguards: a correction reaches the text that cites it, and readiness sorts what is left."""

from uuid import UUID

import pytest

from app.proposals import readiness
from app.proposals import work as rules

ASHA = {"id": str(UUID(int=7)), "name": "Asha"}


def proposal():
    return {
        "facts": {
            "k1": {"subject": "villages", "value": "120 villages", "status": "confirmed", "origin": "vault",
                   "used_in": ["A2", "A4"]},
            "k2": {"subject": "households", "value": "1,240 households", "status": "proposed", "origin": "vault",
                   "used_in": ["A3"]},
            "k3": {"subject": "food-short households", "value": "471 households", "status": "confirmed",
                   "origin": "derived", "from": ["k2"], "used_in": ["A3"]},
        },
        "sections": {
            "A2": {"text": "AJAGAR works in 120 villages of Baksa ⟦k1⟧. It has 412 groups.", "rev": 1},
            "A4": {"text": "The project will reach all 120 ⟦k1⟧.", "rev": 1},
            "A3": {"text": "Of 1240 households ⟦k2⟧, 471 were short of food ⟦k3⟧.", "rev": 2},
        },
    }


class TestACorrection:
    def test_replaces_the_old_value_where_a_sentence_says_it_word_for_word(self):
        out = rules.apply(proposal(), {"facts.k1.correct": "96"}, by=ASHA).work
        assert out["sections"]["A2"]["text"] == "AJAGAR works in 96 villages of Baksa ⟦k4⟧. It has 412 groups."
        assert out["facts"]["k4"]["used_in"] == ["A2"]

    def test_marks_a_part_for_rewriting_where_it_cannot(self):
        out = rules.apply(proposal(), {"facts.k1.correct": "96"}, by=ASHA).work
        assert out["sections"]["A4"]["text"] == "The project will reach all 120 ⟦k1⟧."
        assert out["sections"]["A4"]["needs_rewrite"] is True
        assert out["facts"]["k1"]["used_in"] == ["A4"]

    def test_sends_a_fact_worked_out_from_it_back_to_the_person(self):
        out = rules.apply(proposal(), {"facts.k2.correct": "1,180 households"}, by=ASHA).work
        assert out["sections"]["A3"]["text"].startswith("Of 1,180 households ⟦k4⟧")
        assert out["facts"]["k3"]["status"] == "proposed"

    def test_a_fact_set_aside_marks_every_part_citing_it(self):
        out = rules.apply(proposal(), {"facts.k1.status": "rejected"}, by=ASHA).work
        assert out["sections"]["A2"]["needs_rewrite"] and out["sections"]["A4"]["needs_rewrite"]

    def test_only_sangam_pitch_clears_the_mark(self):
        with pytest.raises(rules.BadChange):
            rules.apply(proposal(), {"sections.A4.needs_rewrite": False}, {"A4": 1}, by=ASHA)


class TestReadiness:
    def test_what_stops_ready_and_what_only_needs_a_look(self):
        work = rules.apply(proposal(), {"facts.k1.correct": "96"}, by=ASHA).work
        work["requirements"] = [{"key": "csr1", "label": "CSR Form 1", "hard": True},
                                {"key": "audits", "label": "Audited accounts", "hard": False}]
        work["gates"] = {"csr1": "yes", "audits": "will_have"}
        work["sections"]["A2"]["score"] = 1
        out = readiness.summary(work)
        assert "Objectives and results: a fact it uses changed, so it needs rewriting" in out["fix_first"]
        assert "1 fact used and not confirmed" in out["fix_first"]
        assert "Audited accounts: promised before sending" in out["worth_checking"]
        assert "Context and target area: one thing missing" in out["worth_checking"]
        assert out["ready"] is False


def test_a_fix_that_would_leave_a_place_untraced_becomes_a_rewrite():
    work = {"facts": {"k4": {"subject": "villages reached", "value": "96 villages", "status": "confirmed",
                             "origin": "vault", "evidence": "96 villages in Udalguri and Baksa, Assam",
                             "used_in": ["A2"]}},
            "sections": {"A2": {"text": "AJAGAR works in 96 villages of Baksa, Assam ⟦k4⟧.", "rev": 1}}}
    out = rules.apply(work, {"facts.k4.correct": "100"}, by=ASHA, districts={"baksa"}).work
    assert out["sections"]["A2"]["text"] == "AJAGAR works in 96 villages of Baksa, Assam ⟦k4⟧."
    assert out["sections"]["A2"]["needs_rewrite"] is True

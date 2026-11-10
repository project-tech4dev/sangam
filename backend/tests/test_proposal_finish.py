"""Finishing's code-only safeguards: polish may change no figure, place, name or gap, and only code saves its result."""

from uuid import UUID

import pytest

from app.proposals import polish, rubric
from app.proposals import work as rules

ASHA = {"id": str(UUID(int=7)), "name": "Asha"}
BUDGET = next(s for s in rubric.sections_for(False) if s.code == "A15")
PLACE = next(s for s in rubric.CORE if s.code == "A2")
WRITTEN = [(BUDGET, "The budget is ₹4.2 crore over 3 years from 2026. [Add: audited accounts for 2024-25]"),
           (PLACE, "AJAGAR works in 96 villages of Baksa, Assam, with Tata Trusts.")]


def changed(budget, place):
    return polish.differences(WRITTEN, {"A15": budget, "A2": place}, districts={"baksa", "udalguri"},
                              names={"ajagar", "tata trusts"})


class TestThePolishCheck:
    def test_the_same_claims_in_new_words_pass(self):
        assert changed("From 2026, over 3 years, the budget is ₹420 lakh. [Add: audited accounts for 2024-25]",
                       "With Tata Trusts, AJAGAR works in 96 villages of Baksa, Assam.") == []

    def test_a_figure_that_changed_is_refused(self):
        assert changed("The budget is ₹42 lakh over 3 years from 2026. [Add: audited accounts for 2024-25]",
                       WRITTEN[1][1]) == ["Budget: 4.2 crore became 42 lakh"]

    def test_a_year_place_name_or_gap_that_moved_is_refused(self):
        out = changed("The budget is ₹4.2 crore over 3 years from 2025.",
                      "AJAGAR works in 96 villages of Udalguri, Assam.")
        assert out == ["Budget: dropped 2026, the gap “audited accounts for 2024-25”", "Budget: added 2025",
                       "Context and target area: dropped Baksa, Tata Trusts",
                       "Context and target area: added Udalguri"]

    def test_a_part_left_out_is_refused(self):
        assert polish.differences(WRITTEN, {"A15": WRITTEN[0][1]}) == ["Context and target area: left out"]


def test_only_code_saves_the_smoothed_wording_or_a_version():
    with pytest.raises(rules.BadChange):
        rules.apply({}, {"polished": {"parts": {"A2": "x"}}}, by=ASHA)
    with pytest.raises(rules.BadChange):
        rules.apply({"versions": []}, {"versions": [{"n": 1}]}, by=ASHA)
    one = rules.apply({"versions": []}, {"versions": [{"n": 1, "title": "Version 1"}]}, by=ASHA, via="version").work
    with pytest.raises(rules.BadChange, match="same moment"):
        rules.apply(one, {"versions": [{"n": 1, "title": "Version 1"}]}, by=ASHA, via="version")

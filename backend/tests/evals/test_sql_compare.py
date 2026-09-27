"""The eval comparator, tested with no model calls and no database."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.evals.sql_compare import (
    answer_contains_value,
    cells_equal,
    gold_satisfied,
    result_sets_match,
)


class TestCellEquality:
    @pytest.mark.parametrize(
        "a,b",
        [(700, 700.0), (Decimal(700), 700), ("700", 700), (Decimal("15000000.00"), 15000000)],
        ids=["int/float", "decimal/int", "str/int", "money"],
    )
    def test_same_number_in_any_representation(self, a, b):
        assert cells_equal(a, b)

    def test_case_insensitive_labels(self):
        assert cells_equal("Assam", "assam")

    def test_a_label_the_agent_elaborated(self):
        assert cells_equal("assam", "Assam (state)")

    def test_short_strings_do_not_match_by_substring(self):
        """Otherwise 'a' matches every label in the database."""
        assert not cells_equal("a", "assam")

    def test_genuinely_different_values_do_not_match(self):
        assert not cells_equal(214, 215)
        assert not cells_equal("Assam", "Manipur")

    def test_null_only_equals_null(self):
        assert cells_equal(None, None)
        assert not cells_equal(None, 0)


class TestMultisetMatching:
    def test_row_order_does_not_matter(self):
        assert result_sets_match([("a", 1), ("b", 2)], [("b", 2), ("a", 1)])

    def test_a_missing_row_fails(self):
        assert not result_sets_match([("a", 1), ("b", 2)], [("a", 1)])

    def test_an_extra_row_fails(self):
        """Over-retrieval is the Assam failure; it must not score as correct."""
        assert not result_sets_match([("a", 1)], [("a", 1), ("b", 2)])


class TestScalarGold:
    GOLD = ((7,),)

    def test_matching_value_stated_in_the_answer(self):
        assert gold_satisfied(self.GOLD, [{"n": 7}], "There are 7 organisations.")

    def test_right_number_never_stated_is_not_an_answer(self):
        """The rows are only evidence; the answer is what the user reads."""
        assert not gold_satisfied(self.GOLD, [{"n": 7}], "Here is a table of results.")

    def test_a_count_answered_by_a_breakdown_of_that_many_rows(self):
        rows = [{"state": f"s{i}"} for i in range(7)]
        assert gold_satisfied(self.GOLD, rows, "They work across 7 states.")

    def test_thousands_separators_in_the_answer(self):
        assert gold_satisfied([(1284,)], [{"n": 1284}], "You ran **1,284** surveys.")

    def test_wrong_number_fails(self):
        assert not gold_satisfied(self.GOLD, [{"n": 8}], "There are 8 organisations.")


class TestEnrichmentIsTolerated:
    """Agents add context columns. That is presentation, not a wrong answer."""

    def test_extra_columns_are_allowed(self):
        gold = [("Tata Trusts", 1), ("SBI Foundation", 1)]
        agent = [
            {"id": 4, "name": "Tata Trusts", "grants": 1},
            {"id": 3, "name": "SBI Foundation", "grants": 1},
        ]
        assert gold_satisfied(gold, agent, "Tata Trusts and SBI Foundation have 1 each.")

    def test_a_limit_1_gold_answered_by_a_full_ranking(self):
        gold = [("Tata Trusts", 12)]
        agent = [
            {"name": "Tata Trusts", "n": 12},
            {"name": "SBI Foundation", "n": 9},
        ]
        assert gold_satisfied(gold, agent, "Tata Trusts leads with 12.")

    def test_but_wrong_values_still_fail(self):
        gold = [("Tata Trusts", 1), ("SBI Foundation", 1)]
        agent = [{"name": "Tata Trusts", "grants": 5}, {"name": "SBI Foundation", "grants": 1}]
        assert not gold_satisfied(gold, agent, "Tata Trusts has 5.")


class TestLabelTolerance:
    def test_agent_invented_its_own_labels_but_the_numbers_identify_the_rows(self):
        gold = [("Q3", 10.0), ("Q4", 20.0)]
        agent = [{"period": "Oct-Dec 2025", "n": 10}, {"period": "Jan-Mar 2026", "n": 20}]
        assert gold_satisfied(gold, agent, "Q3 had 10 and Q4 had 20.")

    def test_not_tolerated_when_the_numbers_repeat(self):
        """With equal numbers the labels are what distinguishes the rows."""
        gold = [("Q3", 10.0), ("Q4", 10.0)]
        agent = [{"period": "Oct-Dec", "n": 10}, {"period": "Jan-Mar", "n": 10}]
        assert not gold_satisfied(gold, agent, "Q3 had 10 and Q4 had 10.")

    def test_not_tolerated_when_the_labels_are_never_stated(self):
        gold = [("Q3", 10.0), ("Q4", 20.0)]
        agent = [{"period": "Oct-Dec", "n": 10}, {"period": "Jan-Mar", "n": 20}]
        assert not gold_satisfied(gold, agent, "The numbers are 10 and 20.")


class TestEmptyResults:
    def test_empty_gold_needs_an_empty_result(self):
        assert gold_satisfied([], [], "I have no data on that.")

    def test_rows_where_the_gold_has_none_fails(self):
        assert not gold_satisfied([], [{"n": 1}], "Found one.")

    def test_no_rows_where_the_gold_has_some_fails(self):
        """The false-zero case: an empty result must never score as correct."""
        assert not gold_satisfied([("a", 1)], [], "There is no data.")


def test_answer_contains_value_handles_money():
    assert answer_contains_value("The grant was ₹15,000,000.", Decimal(15000000))
    assert not answer_contains_value("The grant was ₹15,000,000.", Decimal(16000000))


class TestDeclineDetection:
    """must_decline gates the honest-failure cases, so a loose matcher would let
    a fabricated answer through — the exact regression those cases exist for."""

    @pytest.mark.parametrize(
        "answer",
        [
            "I don't have data on that.",
            "Pratham is not in the registry.",
            "There is no news linked to KABIL in the database.",
            "There is no such table; I cannot query it.",
            # Verbatim from real runs — the matcher was originally written
            # against invented phrasings and missed both of these.
            'There is no table called "checkpoints" in this database.',
            "There is no news coverage linked to KABIL in the registry.",
        ],
    )
    def test_recognises_a_decline(self, answer):
        from tests.evals.harness import _declines

        assert _declines(answer.lower())

    @pytest.mark.parametrize(
        "answer",
        [
            "There are 7 organisations, no caveats.",
            "Tata Trusts has 1 grant and SBI Foundation has 1.",
            "KABIL scored 93, the highest in the cohort.",
            "Pratham was founded in 1995 and runs Read India.",
        ],
    )
    def test_does_not_mistake_an_answer_for_a_decline(self, answer):
        from tests.evals.harness import _declines

        assert not _declines(answer.lower())

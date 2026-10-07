"""Gate, score and order from an assessor's checks: pure arithmetic, so the same checks give the same verdict."""

from __future__ import annotations

import pytest

from app.agent.scoring import WEIGHTS, evaluate

ALL_MET = [
    ("area", "met", "district"),
    ("theme", "met", None),
    ("programme", "met", None),
    ("reg_12a", "met", None),
    ("reg_80g", "met", None),
    ("csr_1", "met", None),
    ("darpan", "met", None),
    ("pan", "met", None),
    ("reg_no", "met", None),
    ("audits_3y", "met", None),
    ("itr_7", "met", None),
    ("board", "met", None),
    ("team_cvs", "met", None),
    ("projects_3", "met", None),
]


def _with(facts, *replace):
    """ALL_MET with some codes swapped out: _with(ALL_MET, ("reg_12a", "unknown", None))."""
    swap = {f[0]: f for f in replace}
    return [swap.get(f[0], f) for f in facts] + [f for f in replace if f[0] not in {g[0] for g in facts}]


def _without(facts, *codes):
    return [f for f in facts if f[0] not in codes]


def _eval(facts, funder_type="corporate_csr", s135=None, shared_districts=0, funder_id=2):
    return evaluate(facts, funder_type=funder_type, section_135_bound=s135,
                    shared_districts=shared_districts, funder_id=funder_id)


def test_the_weights_add_to_100():
    assert sum(w for w, _ in WEIGHTS.values()) == 100


def test_everything_met_scores_100_and_passes():
    r = _eval(ALL_MET)
    assert (r.gate, r.score, r.coverage) == ("pass", 100, 1.0)
    assert r.breakdown == {"fit": 40, "compliance": 25, "financial": 15, "governance": 10, "programme": 10}


class TestAreaPartialCredit:
    @pytest.mark.parametrize("level,points", [("district", 20), ("state", 12), ("pan_india", 6), ("regional", 6)])
    def test_area_is_graded_by_level(self, level, points):
        r = _eval(_with(ALL_MET, ("area", "met", level)))
        assert r.breakdown["fit"] == 20 + points

    def test_an_unknown_area_earns_nothing(self):
        assert _eval(_with(ALL_MET, ("area", "unknown", None))).breakdown["fit"] == 20


class TestFitGate:
    def test_one_met_fit_check_passes(self):
        facts = _with(ALL_MET, ("area", "fail", None), ("theme", "met", None), ("programme", "unknown", None))
        assert _eval(facts).gate == "pass"

    def test_all_three_failing_removes_the_funder(self):
        facts = _with(ALL_MET, ("area", "fail", None), ("theme", "fail", None), ("programme", "fail", None))
        r = _eval(facts)
        assert r.gate == "fail"
        assert any(reason.startswith("fit") for reason in r.gate_reasons)

    def test_failures_mixed_with_unknowns_are_unverified_never_fail(self):
        facts = _with(ALL_MET, ("area", "fail", None), ("theme", "fail", None), ("programme", "unknown", None))
        assert _eval(facts).gate == "unverified"

    def test_a_missing_fit_check_counts_as_unknown(self):
        facts = _with(_without(ALL_MET, "programme"), ("area", "fail", None), ("theme", "fail", None))
        assert _eval(facts).gate == "unverified"


class TestStatutoryGate:
    def test_an_unknown_registration_is_unverified_for_a_csr_funder(self):
        r = _eval(_with(ALL_MET, ("reg_12a", "unknown", None)))
        assert r.gate == "unverified"
        assert any("reg_12a" in reason for reason in r.gate_reasons)

    def test_a_cancelled_registration_removes_a_csr_funder(self):
        assert _eval(_with(ALL_MET, ("reg_80g", "fail", None))).gate == "fail"

    def test_a_statutory_check_left_out_is_unknown(self):
        assert _eval(_without(ALL_MET, "csr_1")).gate == "unverified"

    def test_a_corporate_foundation_is_held_to_it_too(self):
        assert _eval(_with(ALL_MET, ("csr_1", "fail", None)), funder_type="corporate_foundation").gate == "fail"

    def test_section_135_applies_it_whatever_the_type(self):
        assert _eval(_with(ALL_MET, ("csr_1", "fail", None)), funder_type="other", s135=True).gate == "fail"

    def test_a_private_foundation_is_not_held_to_it(self):
        facts = _with(ALL_MET, ("csr_1", "fail", None), ("audits_3y", "unknown", None))
        assert _eval(facts, funder_type="private_foundation").gate == "pass"

    @pytest.mark.parametrize("funder_type", [None, "other"])
    def test_an_unknown_funder_is_unverified_not_skipped(self, funder_type):
        # Skipping would let a funder nobody has typed outrank every known corporate.
        r = _eval(ALL_MET, funder_type=funder_type, s135=None)
        assert r.gate == "unverified"
        assert any("funder type" in reason for reason in r.gate_reasons)

    def test_an_untyped_funder_known_not_to_be_section_135_is_not_held_to_it(self):
        assert _eval(_with(ALL_MET, ("csr_1", "fail", None)), funder_type=None, s135=False).gate == "pass"


class TestConditionalGates:
    def test_turnover_is_checked_only_when_returned(self):
        assert _eval(ALL_MET).gate == "pass"
        assert _eval(ALL_MET + [("turnover", "fail", None)]).gate == "fail"
        assert _eval(ALL_MET + [("turnover", "unknown", None)]).gate == "unverified"

    def test_any_failing_funder_bar_removes_the_funder(self):
        facts = ALL_MET + [("funder_bar", "met", None), ("funder_bar", "fail", None)]
        assert _eval(facts).gate == "fail"


class TestApplicability:
    def test_csr_1_drops_out_of_compliance_for_a_non_csr_funder(self):
        # Six compliance checks remain, all met: the full 25.
        facts = _without(ALL_MET, "csr_1")
        assert _eval(facts, funder_type="private_foundation").breakdown["compliance"] == 25

    def test_turnover_joins_financial_only_when_returned(self):
        r = _eval(ALL_MET + [("turnover", "unknown", None)])
        assert r.breakdown["financial"] == 10
        assert r.coverage < 1

    def test_unknowns_lower_coverage_not_the_gate_alone(self):
        facts = _with(ALL_MET, ("board", "unknown", None), ("team_cvs", "unknown", None))
        r = _eval(facts)
        assert r.gate == "pass"
        assert r.breakdown["governance"] == 0
        assert r.coverage == pytest.approx(12 / 14, abs=0.01)


class TestRankKey:
    def test_it_sorts_in_key_order(self):
        passed_low = _eval(_with(ALL_MET, ("board", "unknown", None)), funder_id=9)
        passed_high = _eval(ALL_MET, funder_id=7)
        unverified = _eval(_with(ALL_MET, ("reg_12a", "unknown", None)), funder_id=1)
        more_districts = _eval(ALL_MET, shared_districts=3, funder_id=8)
        lower_id = _eval(ALL_MET, funder_id=3)
        order = sorted([unverified, passed_low, passed_high, more_districts, lower_id], key=lambda r: r.rank_key)
        assert order == [more_districts, lower_id, passed_high, passed_low, unverified]

    def test_a_failed_funder_sorts_last(self):
        failed = _eval(_with(ALL_MET, ("reg_80g", "fail", None)))
        unverified = _eval(_with(ALL_MET, ("reg_12a", "unknown", None), ("area", "unknown", None)))
        assert sorted([failed, unverified], key=lambda r: r.rank_key) == [unverified, failed]

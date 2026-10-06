"""What a funder-assessor may hand back: the shape is code, the judgement is the model's."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.assessment import FunderAssessment


def _check(**over) -> dict:
    return {"code": "reg_12a", "outcome": "met", "basis": "recorded", "cites": ["[org:126]"]} | over


def _assessment(**over) -> dict:
    return {
        "org_id": 126,
        "funder_id": 2,
        "funder_name": "HDFC Bank Limited",
        "fit_tier": "strong",
        "reasons": ["Both work in Kokrajhar [org:126] [funder:2]"],
        "checks": [_check()],
        "gaps": [],
    } | over


def test_a_complete_assessment_validates():
    a = FunderAssessment.model_validate(_assessment())
    assert a.fit_tier == "strong"
    assert a.checks[0].outcome == "met"


def test_an_unknown_field_is_refused():
    with pytest.raises(ValidationError):
        FunderAssessment.model_validate(_assessment(score=82))


@pytest.mark.parametrize("tier", ["strong", "possible", "weak", "not_enough_recorded"])
def test_the_four_tiers_are_accepted(tier):
    assert FunderAssessment.model_validate(_assessment(fit_tier=tier)).fit_tier == tier


def test_a_tier_outside_the_four_is_refused():
    with pytest.raises(ValidationError):
        FunderAssessment.model_validate(_assessment(fit_tier="excellent"))


def test_a_bare_cite_is_bracketed_so_the_supervisor_repeats_a_real_marker():
    a = FunderAssessment.model_validate(_assessment(checks=[_check(cites=["org:9", "[funder:2]"])]))
    assert a.checks[0].cites == ["[org:9]", "[funder:2]"]


class TestOnlyPositiveEvidenceFails:
    """'We could not find it' is a statement about our research, not about the NGO."""

    def test_a_fail_without_a_citation_is_refused(self):
        with pytest.raises(ValidationError, match="cite"):
            FunderAssessment.model_validate(
                _assessment(checks=[_check(outcome="fail", cites=[])])
            )

    def test_a_fail_resting_on_absence_is_refused(self):
        with pytest.raises(ValidationError, match="unknown"):
            FunderAssessment.model_validate(
                _assessment(checks=[_check(outcome="fail", basis="searched_not_found")])
            )

    def test_an_unknown_needs_no_citation(self):
        a = FunderAssessment.model_validate(
            _assessment(checks=[_check(outcome="unknown", basis="not_researched", cites=[])])
        )
        assert a.checks[0].outcome == "unknown"

    def test_an_unknown_cannot_claim_evidence_was_recorded(self):
        with pytest.raises(ValidationError):
            FunderAssessment.model_validate(
                _assessment(checks=[_check(outcome="unknown", basis="recorded")])
            )

    def test_a_met_without_a_citation_is_refused(self):
        with pytest.raises(ValidationError, match="cite"):
            FunderAssessment.model_validate(_assessment(checks=[_check(cites=[])]))

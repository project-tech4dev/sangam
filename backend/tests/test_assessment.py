"""The assessment compare_fit builds: the checks are validated, the verdict is computed."""

from __future__ import annotations

import json

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
        "funder_type": "corporate_csr",
        "section_135_bound": True,
        "shared_districts": 1,
        "reasons": ["Both work in Kokrajhar [org:126] [funder:2]"],
        "checks": [_check()],
        "gaps": [],
    } | over


def test_a_complete_assessment_validates():
    a = FunderAssessment.model_validate(_assessment())
    assert a.checks[0].outcome == "met"
    assert a.gate == "unverified"  # one check of fourteen is recorded


@pytest.mark.parametrize("field", ["score", "gate", "rank_key", "fit_tier"])
def test_a_computed_or_retired_field_is_refused(field):
    # extra="forbid": a score set by hand cannot ride in beside the computed one.
    with pytest.raises(ValidationError):
        FunderAssessment.model_validate(_assessment(**{field: "x"}))


class TestTheVerdictIsComputed:
    COMPUTED = ("gate", "gate_reasons", "score", "breakdown", "coverage", "rank_key")

    def test_the_model_is_never_asked_for_it(self):
        # ToolStrategy builds the model's tool from the validation schema.
        props = FunderAssessment.model_json_schema()["properties"]
        assert not set(self.COMPUTED) & set(props)

    def test_the_supervisor_receives_it(self):
        # deepagents hands a subagent's structured_response back as model_dump_json().
        data = json.loads(FunderAssessment.model_validate(_assessment()).model_dump_json())
        assert set(self.COMPUTED) <= set(data)

    def test_it_follows_the_checks(self):
        a = FunderAssessment.model_validate(
            _assessment(checks=[_check(code="area", level="district", cites=["[org:126]"]),
                                _check(code="reg_80g", outcome="fail")])
        )
        assert a.gate == "fail"
        assert a.breakdown["fit"] == 20


class TestAreaLevel:
    def test_a_met_area_needs_a_level(self):
        with pytest.raises(ValidationError, match="level"):
            FunderAssessment.model_validate(_assessment(checks=[_check(code="area")]))

    def test_a_level_belongs_only_on_a_met_area(self):
        with pytest.raises(ValidationError, match="level"):
            FunderAssessment.model_validate(_assessment(checks=[_check(level="state")]))
        with pytest.raises(ValidationError, match="level"):
            FunderAssessment.model_validate(
                _assessment(checks=[_check(code="area", outcome="unknown", basis="not_researched",
                                           cites=[], level="state")])
            )


def test_a_code_twice_is_refused_except_funder_bar():
    with pytest.raises(ValidationError, match="twice"):
        FunderAssessment.model_validate(_assessment(checks=[_check(), _check()]))
    bars = [_check(code="funder_bar", note="id 4"), _check(code="funder_bar", note="id 5")]
    assert len(FunderAssessment.model_validate(_assessment(checks=bars)).checks) == 2


def test_a_check_code_outside_the_checklist_is_refused():
    # The A3 gate returned csr1 for csr_1; a comparison table keyed on codes splits on that.
    with pytest.raises(ValidationError):
        FunderAssessment.model_validate(_assessment(checks=[_check(code="csr1")]))


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

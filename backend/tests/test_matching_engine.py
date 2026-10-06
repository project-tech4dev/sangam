"""The engine combines checks: three-valued groups, gates, a weighted score range, a fixed order."""

from __future__ import annotations

import itertools

import pytest

from app.matching.config import load_yaml, parse_criteria
from app.matching.engine import assess, combine, rank_key
from app.matching.evidence import Doc, Fact, FunderEvidence, OrgEvidence, PairFit
from app.matching.models import FunderRef, OrgRef

KABIL = OrgRef(id=9, name="KABIL")


def hdfc(fid=2, ftype="corporate_csr", **fit):
    return FunderEvidence(funder=FunderRef(id=fid, name=f"F{fid}", funder_type=ftype), fit=PairFit(**fit))


def ident(t):
    return Fact(key=t, value="X", basis="recorded", cite="[org:9]")


SPEC_EXAMPLE = {
    "set": "t", "version": 1, "engine": 1,
    "checks": [
        {"code": "area", "label": "a", "evaluator": "shares_place"},
        {"code": "theme", "label": "t", "evaluator": "shares_theme"},
        {"code": "prog", "label": "p", "evaluator": "shares_programme_theme"},
        {"code": "reg_12a", "label": "12a", "evaluator": "has_identifier", "params": {"id_type": "12a"}},
        {"code": "reg_80g", "label": "80g", "evaluator": "has_identifier", "params": {"id_type": "80g"}},
        {"code": "csr_1", "label": "csr1", "evaluator": "has_identifier", "params": {"id_type": "csr1"}},
        {"code": "audits", "label": "au", "evaluator": "min_audited_years", "params": {"years": 3}},
        {"code": "turnover", "label": "tu", "evaluator": "has_document", "params": {"doc_type": "x"}},
        {"code": "board", "label": "b", "evaluator": "min_board", "params": {"count": 3}},
        {"code": "cvs", "label": "c", "evaluator": "has_document", "params": {"doc_type": "team_cv"}},
        {"code": "projects_3", "label": "pr", "evaluator": "min_projects", "params": {"count": 3}},
    ],
    "groups": {"fit": {"min_met": 1, "of": ["area", "theme", "prog"]},
               "statutory": {"all": ["reg_12a", "reg_80g", "csr_1", "audits"]}},
    "roles": {"gate": ["fit", "statutory"]},
    "applies": {"statutory": {"funder_type": ["corporate_csr"]}, "turnover": {"funder_type": ["government"]}},
    "weights": {
        "fit": {"weight": 40, "checks": {"area": 20, "theme": 12, "prog": 8}},
        "compliance": {"weight": 25, "checks": {"reg_12a": 8, "reg_80g": 7, "csr_1": 10}},
        "financial": {"weight": 15, "checks": {"audits": 10, "turnover": 5}},
        "governance": {"weight": 10, "checks": {"board": 6, "cvs": 4}},
        "programme": {"weight": 10, "checks": {"projects_3": 10}},
    },
    "partial": {"area": {"district": 1.0, "state": 0.6, "pan_india_stated": 0.3}},
    "ranking": ["gate_status", "score_min", "coverage", "shared_districts", "funder_id"],
}
CRITERIA = parse_criteria(SPEC_EXAMPLE)
KABIL_EV = OrgEvidence(org=KABIL, districts={1: "Udalguri"}, states={2: "Assam"},
                       clauses={"csr-education-and-livelihoods": "Education"},
                       identifiers={"12a": ident("12a"), "80g": ident("80g")})


class TestCombinators:
    VALUES = ("met", "fail", "unknown")

    @pytest.mark.parametrize("xs", list(itertools.product(VALUES, repeat=3)))
    def test_all(self, xs):
        want = "fail" if "fail" in xs else "met" if set(xs) == {"met"} else "unknown"
        assert combine({"all": True}, list(xs)) == want

    @pytest.mark.parametrize("xs", list(itertools.product(VALUES, repeat=3)))
    def test_any(self, xs):
        want = "met" if "met" in xs else "fail" if set(xs) == {"fail"} else "unknown"
        assert combine({"any": True}, list(xs)) == want

    @pytest.mark.parametrize("xs", list(itertools.product(VALUES, repeat=3)))
    def test_min_met_two(self, xs):
        met, unknown = xs.count("met"), xs.count("unknown")
        want = "met" if met >= 2 else "fail" if met + unknown < 2 else "unknown"
        assert combine({"min_met": 2}, list(xs)) == want


class TestTheSpecExample:
    """Engine doc §3: met 47 of 95 applicable → 49–100, coverage 49."""

    a = assess(CRITERIA, KABIL_EV, hdfc(shared_districts=("Udalguri",), shared_states=("Assam",),
                                        tag_clauses=("Education",), shared_tag_clauses=("Education",)))

    def test_score_range(self):
        assert (self.a.score_min, self.a.score_max, self.a.coverage) == (49, 100, 49)

    def test_not_applicable_check_drops_out(self):
        turnover = next(c for c in self.a.checks if c.code == "turnover")
        assert turnover.basis == "not_applicable"
        assert sum(b.applicable for b in self.a.breakdown.values()) == 95

    def test_breakdown(self):
        assert self.a.breakdown["fit"].earned == 32
        assert self.a.breakdown["compliance"].unknown == 10

    def test_gate_unknown_is_unverified(self):
        assert self.a.gate_status == "unverified"
        assert self.a.fit_status == "met"

    def test_gaps_gate_first_then_by_weight(self):
        codes = [g.code for g in self.a.gaps]
        assert codes[:2] == ["csr_1", "audits"]
        assert codes.index("projects_3") < codes.index("board") < codes.index("cvs")


def test_state_level_area_earns_partial_credit():
    a = assess(CRITERIA, KABIL_EV, hdfc(shared_states=("Assam",)))
    assert a.breakdown["fit"].earned == 12


def test_zero_evidence_is_zero_to_a_hundred_never_zero():
    a = assess(CRITERIA, OrgEvidence(org=KABIL), hdfc())
    assert (a.score_min, a.score_max, a.coverage) == (0, 100, 0)
    assert a.fit_status == "unknown"
    assert a.gate_status == "unverified"


def test_a_failed_gate_names_itself():
    o = OrgEvidence(org=KABIL, districts={1: "Udalguri"}, clauses={"x": "X"})
    a = assess(CRITERIA, o, hdfc(stated_places=2, tag_clauses=("Sports",), asserted_tag_clauses=("Sports",),
                                tagged_programmes=1, asserted_programmes=1))
    assert (a.gate_status, a.failed_gates) == ("failed", ["fit"])


def test_a_gate_that_does_not_apply_is_skipped():
    a = assess(CRITERIA, KABIL_EV, hdfc(ftype="private_foundation", shared_districts=("Udalguri",)))
    assert a.gate_status == "passed"
    assert {c.basis for c in a.checks if c.code in {"csr_1", "audits"}} == {"not_applicable"}


def test_vault_documents_feed_has_identifier_through_the_engine():
    o = OrgEvidence(org=KABIL, documents={"x": (Doc(id=1, doc_type="x", vault=True),)})
    a = assess(CRITERIA, o, hdfc(ftype="government"))
    assert next(c for c in a.checks if c.code == "turnover").basis == "on_file"


def test_ranking_order():
    passed = assess(CRITERIA, KABIL_EV, hdfc(fid=5, ftype="private_foundation", shared_states=("Assam",)))
    passed_better = assess(CRITERIA, KABIL_EV, hdfc(fid=6, ftype="private_foundation",
                                                    shared_districts=("Udalguri",)))
    unverified = assess(CRITERIA, KABIL_EV, hdfc(fid=3, shared_districts=("Udalguri",)))
    tie_a = assess(CRITERIA, KABIL_EV, hdfc(fid=8, ftype="private_foundation", shared_states=("Assam",)))
    order = sorted([unverified, tie_a, passed, passed_better], key=lambda a: rank_key(a, CRITERIA.ranking))
    assert [a.funder.id for a in order] == [6, 5, 8, 3]


def test_same_inputs_same_bytes():
    f = hdfc(shared_states=("Assam",))
    assert assess(CRITERIA, KABIL_EV, f).model_dump_json() == assess(CRITERIA, KABIL_EV, f).model_dump_json()


def test_the_shipped_criteria_assess():
    criteria, _ = load_yaml()
    a = assess(criteria, KABIL_EV, hdfc(shared_districts=("Udalguri",)))
    assert a.criteria_version == criteria.version
    assert sum(b.applicable for b in a.breakdown.values()) == 100


def test_an_unrecorded_funder_type_keeps_the_statutory_gate():
    a = assess(CRITERIA, OrgEvidence(org=KABIL, districts={1: "Udalguri"}, states={2: "Assam"}),
               hdfc(ftype=None, shared_districts=("Udalguri",)))
    assert next(c for c in a.checks if c.code == "csr_1").basis == "not_researched"
    assert a.gate_status == "unverified"

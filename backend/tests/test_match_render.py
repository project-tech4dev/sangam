"""What the model reads from a match tool: cited, three blocks, unknowns never read as fail."""

from __future__ import annotations

import re
from pathlib import Path

from app.agent.tools import match_render as r
from app.agent.tools.sql.render import MAX_OUTPUT_CHARS
from app.matching.evidence import Doc, Fact, OrgEvidence, OrgProfile
from app.matching.models import (
    Ambiguous,
    Assessment,
    Call,
    CheckResult,
    Dimension,
    FunderList,
    FunderMatch,
    FunderProfile,
    FunderRef,
    OrgRef,
    Resolved,
    Shortlist,
)

ORG = OrgRef(id=9, name="KABIL", slug="kabil")


def check(code, outcome, basis="recorded", reason="not_recorded", category="fit", **params):
    return CheckResult(code=code, label=code.title(), category=category, role="weighted", outcome=outcome,
                       basis=basis, reason_code=reason, reason_params=params, cites=["[org:9]"])


def assessment(fid=2, gate="unverified", **kw):
    checks = [check("area", "met", reason="shared_district", places=["Udalguri"]),
              check("csr_1", "unknown", basis="searched_not_found", reason="searched_not_found",
                    category="compliance", searched_on="2026-10-04"),
              check("board", "fail", reason="count_short", category="governance", have=2, need=3)]
    return Assessment(criteria_version=1, criteria_hash="abcdef123456", org=ORG,
                      funder=FunderRef(id=fid, name=f"Funder {fid}"), gate_status=gate, fit_status="met",
                      checks=checks, score_min=49, score_max=100, coverage=49, breakdown={},
                      gaps=[checks[2], checks[1]], **kw)


def shortlist(ranked=None, thin=(), failed=()):
    ranked = [assessment()] if ranked is None else ranked
    return Shortlist(criteria_version=1, criteria_hash="abcdef123456", org=ORG, ranked=ranked,
                     not_enough_recorded=list(thin), did_not_pass=list(failed),
                     total_funders=len(ranked) + len(thin) + len(failed), offset=0, limit=10)


class TestShortlist:
    def test_three_blocks_always_print_with_counts(self):
        out = r.render_shortlist(shortlist())
        assert "RANKED (1)" in out and "NOT ENOUGH RECORDED TO RANK (0)" in out and "DID NOT PASS (0)" in out

    def test_every_unrankable_funder_is_named_and_cited(self):
        thin = [FunderRef(id=i, name=f"Thin {i}") for i in range(30, 50)]
        out = r.render_shortlist(shortlist(thin=thin))
        assert all(f"Thin {i} [funder:{i}]" in out for i in range(30, 50))

    def test_states_the_criteria_version_and_that_the_score_is_computed(self):
        out = r.render_shortlist(shortlist())
        assert "criteria v1" in out and "score 49–100" in out and "computed by Sangam" in out

    def test_a_failed_funder_names_the_gate(self):
        failed = assessment(fid=7, gate="failed", failed_gates=["fit"])
        assert "Funder 7 [funder:7]" in r.render_shortlist(shortlist(failed=[failed]))

    def test_the_orgs_own_gaps_are_listed_once(self):
        out = r.render_shortlist(shortlist(ranked=[assessment(2), assessment(3)]))
        assert out.count("searched 2026-10-04, not found") == 1


class TestAssessments:
    def test_every_check_prints_with_its_cite(self):
        out = r.render_assessments([assessment()])
        assert "Area" in out and "Csr_1" in out and "Board" in out and "[org:9]" in out

    def test_an_unknown_never_reads_as_fail(self):
        line = next(x for x in r.render_assessments([assessment()]).splitlines() if "Csr_1" in x)
        assert "fail" not in line.lower() and "searched 2026-10-04, not found" in line

    def test_a_fail_reads_as_fail_with_the_numbers(self):
        line = next(x for x in r.render_assessments([assessment()]).splitlines() if "Board" in x)
        assert "fail" in line.lower() and "board of 2, needs 3" in line

    def test_more_than_one_funder_gets_a_side_by_side_table(self):
        out = r.render_assessments([assessment(2), assessment(3)])
        assert "| check | Funder 2 [funder:2] | Funder 3 [funder:3] |" in out


class TestProfiles:
    def test_an_empty_org_says_not_recorded_per_field(self):
        out = r.render_org(OrgProfile(OrgEvidence(org=ORG)))
        assert out.startswith("KABIL [org:9]") and out.count("not recorded") >= 6

    def test_org_facts_carry_values_and_vault_status(self):
        ev = OrgEvidence(org=ORG, districts={1: "Udalguri"}, states={2: "Assam"},
                         identifiers={"12a": Fact("12a", "AAAT1234E", "recorded", "[org:9]")},
                         documents={"csr1_certificate": (Doc(5, "csr1_certificate", True),)})
        out = r.render_org(OrgProfile(ev, registered="Udalguri"))
        assert "Udalguri" in out and "AAAT1234E" in out and "on file in the Vault" in out

    def test_an_empty_funder_says_no_eligibility_bars_recorded(self):
        out = r.render_funder(FunderProfile(funder=FunderRef(id=2, name="HDFC Bank")))
        assert out.startswith("HDFC Bank [funder:2]") and "no eligibility bars recorded" in out

    def test_money_is_rupees_in_indian_grouping(self):
        assert r.inr(1200000) == "₹12,00,000" and r.inr(999) == "₹999" and r.inr(None) == "not recorded"

    def test_a_passed_deadline_is_shown_not_hidden(self):
        pf = FunderProfile(funder=FunderRef(id=2, name="F"),
                           calls=[Call(id=1, title="Call one", deadline="2026-07-07", deadline_passed=True)])
        assert "Call one (deadline 2026-07-07, passed)" in r.render_funder(pf)


class TestFunderList:
    def lst(self):
        dim = Dimension(outcome="met", basis="recorded", reason_code="shared_state", level="state",
                        reason_params={"places": ["Assam"]})
        unk = Dimension(outcome="unknown", basis="not_researched", reason_code="funder_places_not_recorded")
        return FunderList(places=["Assam"], themes=[], funder_types=[], matched_total=1, no_overlap=5,
                          matched=[FunderMatch(funder=FunderRef(id=2, name="A"), outcome="met", dims={"place": dim})],
                          not_recorded=[FunderMatch(funder=FunderRef(id=3, name="B"), outcome="unknown",
                                                    dims={"place": unk})],
                          total_funders=7, offset=0, limit=20)

    def test_counts_and_blocks(self):
        out = r.render_funders(self.lst())
        assert "1 match, 1 not recorded, 5 no overlap (7 funders)" in out
        assert "A [funder:2]" in out and "B [funder:3]" in out and "shares a state: Assam" in out


class TestAmbiguous:
    def test_candidates_are_cited_and_the_model_is_told_to_ask(self):
        a = Ambiguous(kind="org", text="assam trust", candidates=[Resolved(kind="org", id=4, name="X Trust"),
                                                                 Resolved(kind="org", id=5, name="Y Trust")])
        out = r.render_ambiguous(a)
        assert "X Trust [org:4]" in out and "Y Trust [org:5]" in out and "ask" in out.lower()

    def test_no_candidates_says_so(self):
        out = r.render_ambiguous(Ambiguous(kind="funder", text="qqq", candidates=[]))
        assert "No funder" in out


def test_output_is_capped_with_a_note():
    out = r.render_shortlist(shortlist(ranked=[assessment(i) for i in range(400)]))
    assert len(out) <= MAX_OUTPUT_CHARS + 200 and "output cut" in out


def test_every_reason_code_has_a_phrase():
    from app.matching.evaluators import _ACTIVE, _LAPSED

    src = (Path(r.__file__).parents[2] / "matching" / "evaluators.py").read_text()
    literal = set(re.findall(r'Check\("(?:met|fail|unknown)", [^,]+, "(\w+)"', src))
    literal |= set(re.findall(r'_unknown\("(\w+)"', src))
    codes = literal | _ACTIVE | _LAPSED | {"not_applicable", "funder_type", "funder_type_not_recorded"}
    assert len(literal) > 20, "the scan found too few codes to be scanning the right thing"
    assert codes <= set(r.REASONS), sorted(codes - set(r.REASONS))

"""Evaluators are pure: hand-built evidence in, one Check out."""

from __future__ import annotations

from datetime import date

from app.matching.evaluators import REGISTRY, run
from app.matching.evidence import (
    FUNDER_KINDS,
    ORG_KINDS,
    PAIR_KINDS,
    Doc,
    Fact,
    FunderEvidence,
    OrgEvidence,
    PairFit,
    Project,
)
from app.matching.models import FunderRef, OrgRef

KABIL = OrgRef(id=9, name="KABIL")
HDFC = FunderRef(id=2, name="HDFC Bank", funder_type="corporate_csr")


def org(**kw) -> OrgEvidence:
    return OrgEvidence(org=KABIL, **kw)


def funder(**kw) -> FunderEvidence:
    return FunderEvidence(funder=HDFC, fit=PairFit(**kw))


def check(name, o, f=None, **params):
    return run(name, o, f or funder(), params)


class TestHasIdentifier:
    def test_nothing_recorded_is_unknown_not_researched(self):
        c = check("has_identifier", org(), id_type="12a")
        assert (c.outcome, c.basis) == ("unknown", "not_researched")

    def test_a_current_identifier_is_met_and_cited(self):
        o = org(identifiers={"12a": Fact(key="12a", value="AAAT1234E", basis="recorded", cite="[org:9]")})
        c = check("has_identifier", o, id_type="12a")
        assert (c.outcome, c.basis) == ("met", "recorded")
        assert "[org:9]" in c.cites

    def test_a_cancelled_event_is_a_fail(self):
        o = org(
            identifiers={"12a": Fact(key="12a", value="AAAT1234E", basis="recorded", cite="[org:9]")},
            credential_events={"12a": Fact(key="12a", value="cancelled", basis="recorded", cite="[org:9]",
                                           as_of="2026-01-04")},
        )
        c = check("has_identifier", o, id_type="12a")
        assert (c.outcome, c.reason_code) == ("fail", "cancelled")

    def test_an_event_saying_not_found_is_searched_not_found(self):
        o = org(credential_events={"csr1": Fact(key="csr1", value="not_found", basis="recorded",
                                                cite="[org:9]", as_of="2026-10-04")})
        c = check("has_identifier", o, id_type="csr1")
        assert (c.outcome, c.basis) == ("unknown", "searched_not_found")
        assert c.reason_params["searched_on"] == "2026-10-04"

    def test_research_not_found_naming_the_credential_is_searched_not_found(self):
        o = org(not_found=(("12A registration certificate", date(2026, 10, 4)),))
        c = check("has_identifier", o, id_type="12a")
        assert (c.outcome, c.basis) == ("unknown", "searched_not_found")
        assert c.reason_params["searched_on"] == "2026-10-04"

    def test_a_vault_certificate_is_on_file(self):
        o = org(
            identifiers={"12a": Fact(key="12a", value="AAAT1234E", basis="recorded", cite="[org:9]")},
            documents={"12a_certificate": (Doc(id=7, doc_type="12a_certificate", vault=True),)},
        )
        c = check("has_identifier", o, id_type="12a", doc_type="12a_certificate")
        assert (c.outcome, c.basis) == ("met", "on_file")

    def test_a_vault_certificate_alone_is_on_file(self):
        o = org(documents={"12a_certificate": (Doc(id=7, doc_type="12a_certificate", vault=True),)})
        c = check("has_identifier", o, id_type="12a", doc_type="12a_certificate")
        assert (c.outcome, c.basis) == ("met", "on_file")

    def test_registry_declares_what_it_reads(self):
        assert "org.identifiers" in REGISTRY["has_identifier"].reads


UDALGURI = {101: "Udalguri"}
ASSAM = {11: "Assam"}
LIVELIHOODS = {"csr-education-and-livelihoods": "Education and livelihoods"}


class TestSharesPlace:
    o = org(districts=UDALGURI, states=ASSAM)

    def test_a_shared_district_is_met_at_district_level(self):
        f = funder(shared_districts=("Udalguri",), shared_states=("Assam",), observed_places=2)
        c = check("shares_place", self.o, f)
        assert (c.outcome, c.level) == ("met", "district")

    def test_a_shared_state_only_is_met_at_state_level(self):
        c = check("shares_place", self.o, funder(shared_states=("Assam",), observed_places=1))
        assert (c.outcome, c.level) == ("met", "state")

    def test_stated_pan_india_is_met_at_its_own_level(self):
        c = check("shares_place", self.o, funder(pan_india=True, stated_places=1))
        assert (c.outcome, c.level) == ("met", "pan_india_stated")

    def test_stated_places_with_no_overlap_fail(self):
        c = check("shares_place", self.o, funder(stated_places=3, observed_places=5))
        assert (c.outcome, c.reason_code) == ("fail", "no_overlap_stated")

    def test_footprints_elsewhere_are_not_a_fail(self):
        c = check("shares_place", self.o, funder(observed_places=5))
        assert (c.outcome, c.reason_code) == ("unknown", "no_overlap_observed")

    def test_a_region_alone_is_unknown(self):
        c = check("shares_place", self.o, funder(regions=("Northeast India",), stated_places=1))
        assert (c.outcome, c.reason_code) == ("unknown", "region_membership_not_recorded")

    def test_an_org_with_no_places_is_unknown(self):
        c = check("shares_place", org(), funder(shared_states=("Assam",)))
        assert (c.outcome, c.reason_code) == ("unknown", "org_places_not_recorded")

    def test_a_funder_with_no_places_is_unknown(self):
        c = check("shares_place", self.o, funder())
        assert (c.outcome, c.reason_code) == ("unknown", "funder_places_not_recorded")

    def test_levels_param_is_honoured(self):
        f = funder(shared_states=("Assam",), observed_places=1)
        assert check("shares_place", self.o, f, levels=["district"]).outcome == "unknown"


class TestSharesTheme:
    o = org(clauses=LIVELIHOODS)

    def test_a_shared_clause_is_met(self):
        f = funder(tag_clauses=("Education and livelihoods",), shared_tag_clauses=("Education and livelihoods",))
        c = check("shares_theme", self.o, f)
        assert c.outcome == "met"
        assert c.reason_params["shared"] == ["Education and livelihoods"]

    def test_tagged_but_none_shared_fails(self):
        c = check("shares_theme", self.o, funder(tag_clauses=("Sports",)))
        assert (c.outcome, c.reason_code) == ("fail", "no_shared_theme")

    def test_untagged_funder_or_org_is_unknown(self):
        assert check("shares_theme", self.o, funder()).outcome == "unknown"
        assert check("shares_theme", org(), funder(tag_clauses=("Sports",))).outcome == "unknown"


class TestSharesProgrammeTheme:
    o = org(clauses=LIVELIHOODS)

    def test_met_fail_and_unknown(self):
        met = check("shares_programme_theme", self.o, funder(tagged_programmes=3, shared_programmes=("Parivartan",)))
        fail = check("shares_programme_theme", self.o, funder(tagged_programmes=3))
        unknown = check("shares_programme_theme", self.o, funder())
        assert (met.outcome, fail.outcome, unknown.outcome) == ("met", "fail", "unknown")


def fy(year, audited=True):
    return Fact(key=year, value={"is_audited": audited}, basis="recorded", cite="[org:9]")


class TestMinAuditedYears:
    def test_three_audited_years_is_met(self):
        o = org(financials=(fy("FY2021-22"), fy("FY2022-23"), fy("FY2023-24")))
        assert check("min_audited_years", o, years=3).outcome == "met"

    def test_fewer_recorded_years_is_unknown_not_fail(self):
        o = org(financials=(fy("FY2023-24"), fy("FY2022-23", audited=False)))
        c = check("min_audited_years", o, years=3)
        assert (c.outcome, c.reason_params) == ("unknown", {"have": 1, "need": 3})

    def test_nothing_recorded_is_not_researched(self):
        assert check("min_audited_years", org(), years=3).basis == "not_researched"


def bearer(name):
    return Fact(key=name, value="office_bearer", basis="recorded", cite="[org:9]")


class TestMinBoard:
    def test_two_of_three_fails_with_counts(self):
        c = check("min_board", org(board=(bearer("A"), bearer("B"))), count=3)
        assert (c.outcome, c.reason_code, c.reason_params) == ("fail", "count_short", {"have": 2, "need": 3})

    def test_none_recorded_is_unknown(self):
        assert check("min_board", org(), count=3).outcome == "unknown"

    def test_enough_is_met(self):
        assert check("min_board", org(board=(bearer("A"), bearer("B"), bearer("C"))), count=3).outcome == "met"


class TestHasDocument:
    def test_vault_research_and_none(self):
        vault = org(documents={"policy": (Doc(id=1, doc_type="policy", vault=True),)})
        research = org(documents={"policy": (Doc(id=2, doc_type="policy", vault=False),)})
        assert check("has_document", vault, doc_type="policy").basis == "on_file"
        assert check("has_document", research, doc_type="policy").basis == "recorded"
        assert check("has_document", org(), doc_type="policy").outcome == "unknown"

    def test_requires_on_file_turns_recorded_into_unknown(self):
        research = org(documents={"policy": (Doc(id=2, doc_type="policy", vault=False),)})
        c = check("has_document", research, doc_type="policy", requires="on_file")
        assert (c.outcome, c.basis) == ("unknown", "not_on_file")


ALL = {"funder": True, "amount": True, "theme": True, "duration": True, "results": True}


class TestMinProjects:
    def test_three_complete_is_met(self):
        o = org(projects=tuple(Project("grant", i, f"[grant:{i}]", **ALL) for i in range(3)))
        assert check("min_projects", o, count=3).outcome == "met"

    def test_incomplete_projects_are_unknown_with_counts(self):
        partial = {**ALL, "results": False}
        o = org(projects=(Project("grant", 1, "[grant:1]", **ALL), Project("grant", 2, "[grant:2]", **partial),
                          Project("grant", 3, "[grant:3]", **partial)))
        c = check("min_projects", o, count=3)
        assert (c.outcome, c.reason_params["complete"], c.reason_params["need"]) == ("unknown", 1, 3)

    def test_none_recorded_is_not_researched(self):
        assert check("min_projects", org(), count=3).basis == "not_researched"


def test_every_kind_an_evaluator_reads_has_a_loader():
    loadable = ORG_KINDS | FUNDER_KINDS | PAIR_KINDS
    assert {name: spec.reads - loadable for name, spec in REGISTRY.items() if spec.reads - loadable} == {}

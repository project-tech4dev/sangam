"""Evaluators are pure: hand-built evidence in, one Check out."""

from __future__ import annotations

from datetime import date

from app.matching.evaluators import REGISTRY, run
from app.matching.evidence import Doc, Fact, FunderEvidence, OrgEvidence, PairFit
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

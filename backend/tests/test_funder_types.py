from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.ingest.catalog.promote_records import funder_from
from app.ingest.catalog.rows import FunderRecord
from app.ingest.research.finding_types import IdentityFinding

PROV = {"source_url": "https://x.example.org", "source_name": "r", "fetched_at": datetime(2026, 11, 25, tzinfo=UTC),
        "content_hash": "h", "extractor_version": "v"}


@pytest.mark.parametrize("stored, promoted", [
    ("corporate_csr", "csr_company"), ("corporate_foundation", "csr_foundation"),
    ("family_trust", "private_foundation"), ("family_trust_network", "private_foundation"),
    ("international_agency", "international_agency"), ("impact_investor", "other"), ("", None), (None, None),
])
def test_a_brief_saved_before_0064_promotes_to_the_new_types(stored, promoted):
    assert FunderRecord(name="Misereor", funder_type=stored, **PROV).funder_type == promoted


def test_a_new_save_must_use_one_of_the_nine():
    fields = {"name": "Misereor", "source_url": "https://www.misereor.org", "confidence": "high", "evidence": "Misereor is the German "
              "Catholic Bishops' Organisation for Development Cooperation."}
    assert IdentityFinding.model_validate({**fields, "funder_type": "international_agency"}).funder_type
    with pytest.raises(ValidationError):
        IdentityFinding.model_validate({**fields, "funder_type": "corporate_csr"})


def test_an_old_identity_finding_promotes_as_the_new_type():
    row = {"slug": "tata-trusts", "canonical_name": "Tata Trusts", "entity_name": "Tata Trusts", "website": None,
           "researched_at": datetime(2026, 10, 1, tzinfo=UTC)}
    old = {"concept": "identity", "name": "Tata Trusts", "funder_type": "family_trust_network",
           "source_url": "https://www.tatatrusts.org", "source_name": "Tata Trusts", "confidence": "high",
           "evidence": "Tata Trusts is among India's oldest philanthropic organisations."}
    report = {"reasons": [], "held": []}
    assert funder_from(row, [old], report).funder_type == "private_foundation"


def _identity(funder_type, source_type):
    return {"concept": "identity", "name": "Caring Friends", "funder_type": funder_type, "source_type": source_type,
            "source_url": "https://caringfriends.in", "source_name": "Caring Friends", "confidence": "high",
            "evidence": "Caring Friends is a network of individuals who give to grassroots NGOs."}


def test_a_real_type_from_a_weaker_source_beats_other_from_a_stronger_one():
    row = {"slug": "caring-friends", "canonical_name": "Caring Friends", "entity_name": "Caring Friends",
           "website": None, "researched_at": datetime(2026, 10, 1, tzinfo=UTC)}
    findings = [_identity("impact_investor", "funder"), _identity("hni", "aggregator")]
    assert funder_from(row, findings, {"reasons": [], "held": []}).funder_type == "hni"
    assert funder_from(row, findings[:1], {"reasons": [], "held": []}).funder_type == "other"

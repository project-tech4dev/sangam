from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.ingest.catalog.rows import FunderRecord
from app.ingest.research.finding_types import IdentityFinding

PROV = {"source_url": "https://x.example.org", "source_name": "r", "fetched_at": datetime(2026, 11, 25, tzinfo=UTC),
        "content_hash": "h", "extractor_version": "v"}


@pytest.mark.parametrize("stored, promoted", [
    ("corporate_csr", "csr_company"), ("corporate_foundation", "csr_foundation"),
    ("family_trust", "private_foundation"), ("family_trust_network", "private_foundation"),
    ("international_agency", "international_agency"), ("impact_investor", None), (None, None),
])
def test_a_brief_saved_before_0064_promotes_to_the_new_types(stored, promoted):
    assert FunderRecord(name="Misereor", funder_type=stored, **PROV).funder_type == promoted


def test_a_new_save_must_use_one_of_the_nine():
    fields = {"name": "Misereor", "source_url": "https://www.misereor.org", "confidence": "high", "evidence": "Misereor is the German "
              "Catholic Bishops' Organisation for Development Cooperation."}
    assert IdentityFinding.model_validate({**fields, "funder_type": "international_agency"}).funder_type
    with pytest.raises(ValidationError):
        IdentityFinding.model_validate({**fields, "funder_type": "corporate_csr"})

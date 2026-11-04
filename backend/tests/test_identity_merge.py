"""#308: every identity finding reaches the record, within a run and across runs."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ingest import brief
from app.ingest.promote import funder_from, org_from

NOW = datetime(2026, 10, 22, tzinfo=UTC)
ROW = {"slug": "resilience-fund", "entity_name": "Resilience Fund", "canonical_name": None,
       "researched_at": NOW, "website": None}
ABOUT = "https://resiliencefund.org/about"
FUNDS = "https://resiliencefund.org/what-we-fund"
DEVEX = "https://devex.com/funding/resilience-fund"


def funder(url: str, **fields) -> dict:
    return {"concept": "identity", "source_url": url, "evidence": f"as printed on {url}",
            "confidence": "high", **fields}


def org(url: str, source_type: str, tier: str, **fields) -> dict:
    return {"concept": "org_identity", "source_url": url, "evidence": f"as printed on {url}",
            "confidence": "high", "source_type": source_type, "evidence_tier": tier, **fields}


class TestTagsOnALaterIdentityFindingAreKept:
    def test_a_funder_gets_the_tags_of_its_second_identity_finding(self):
        findings = [
            funder(ABOUT, name="The Resilience Fund for Women in Global Value Chains"),
            funder(FUNDS, name="The Resilience Fund for Women in Global Value Chains",
                   themes=["gender-rights", "climate-adaptation"], populations=["women", "migrant-workers"],
                   lenses=["women_girls"], tag_note="what-we-fund: 'women workers in garment chains'"),
        ]
        rec = funder_from(ROW, findings)
        assert rec.themes == ["gender-rights", "climate-adaptation"]
        assert rec.populations == ["women", "migrant-workers"]
        assert rec.lenses == ["women_girls"]
        assert rec.tag_note == "what-we-fund: 'women workers in garment chains'"

    def test_an_org_gets_the_tags_of_its_second_identity_finding(self):
        findings = [
            org("https://rnba.org", "org_document", "evidenced", name="RNBA"),
            org("https://rnba.org/work", "org_document", "evidenced", name="RNBA",
                themes=["forests-biodiversity", "nrm-water"], populations=["tribal-communities"],
                tag_note="work page: 'forest rights of tribal villages'"),
        ]
        rec = org_from({**ROW, "slug": "rnba"}, findings)
        assert rec.themes == ["forests-biodiversity", "nrm-water"]
        assert rec.populations == ["tribal-communities"]

    def test_lists_are_unioned_and_tag_notes_joined(self):
        findings = [
            funder(ABOUT, name="Resilience Fund", themes=["gender-rights"], populations=["women"],
                   aliases=["TRF"], tag_note="about: 'women's rights'"),
            funder(FUNDS, name="Resilience Fund", themes=["climate-adaptation"], populations=["women"],
                   aliases=["TRF", "Resilience Fund for Women"], tag_note="funds: 'climate adaptation'"),
        ]
        rec = funder_from(ROW, findings)
        assert rec.themes == ["gender-rights", "climate-adaptation"]
        assert rec.populations == ["women"]
        assert rec.aliases == ["TRF", "Resilience Fund for Women"]
        assert rec.tag_note == "about: 'women's rights' · funds: 'climate adaptation'"


class TestScalarsComeFromTheFirstFindingThatStatesThem:
    def test_a_blank_on_the_first_finding_is_filled_from_a_later_one(self):
        findings = [funder(ABOUT, name="Resilience Fund"),
                    funder(DEVEX, name="Resilience Fund", grant_size_max={"value": 50, "unit": "lakh",
                                                                          "text": "₹50 lakh"})]
        assert funder_from(ROW, findings).grant_size_max == 5_000_000

    def test_a_disagreement_keeps_the_first_value_and_says_so(self):
        report = {"reasons": []}
        findings = [funder(ABOUT, name="The Resilience Fund for Women"),
                    funder(DEVEX, name="Resilience Fund")]
        rec = funder_from(ROW, findings, report)
        assert rec.name == "The Resilience Fund for Women"
        assert "Resilience Fund" in rec.aliases
        assert report["reasons"] == [
            f"identity: name 'The Resilience Fund for Women' kept over 'Resilience Fund' ({DEVEX})"]

    def test_an_org_scalar_comes_from_the_stronger_source_whatever_the_order(self):
        findings = [org("https://guidestar.example/rnba", "aggregator", "claimed", name="RNBA",
                        website="https://old-rnba.example"),
                    org("https://rnba.org", "org_document", "evidenced", name="RNBA", website="https://rnba.org")]
        assert org_from({**ROW, "slug": "rnba"}, findings).website == "https://rnba.org"

    def test_an_org_record_is_only_as_strong_as_the_weakest_source_it_carries(self):
        """A claimed website riding on an evidenced name must not overwrite a stored evidenced value."""
        findings = [org("https://rnba.org", "org_document", "evidenced", name="RNBA"),
                    org("https://guidestar.example/rnba", "aggregator", "claimed", name="RNBA",
                        website="https://rnba.example")]
        rec = org_from({**ROW, "slug": "rnba"}, findings)
        assert rec.website == "https://rnba.example"
        assert (rec.source_type, rec.evidence_tier) == ("aggregator", "claimed")
        assert rec.source_url == "https://guidestar.example/rnba"


class TestThemesStayAtThree:
    def test_themes_past_the_third_are_reported_not_tagged(self):
        report = {"reasons": []}
        findings = [funder(ABOUT, name="Resilience Fund", themes=["gender-rights", "climate-adaptation"],
                           tag_note="about"),
                    funder(FUNDS, name="Resilience Fund", themes=["gender-based-violence", "nrm-water"],
                           tag_note="funds")]
        rec = funder_from(ROW, findings, report)
        assert rec.themes == ["gender-rights", "climate-adaptation", "gender-based-violence"]
        assert report["reasons"] == ["identity: theme 'nrm-water' not tagged (at most 3)"]


class TestEveryRunsIdentityReachesPromotion:
    def test_a_weaker_newer_run_with_tags_is_kept_beside_a_stronger_older_one(self):
        older = org("https://pesch.org", "org_document", "evidenced", name="PESCH")
        newer = org("https://directory.example/pesch", "aggregator", "claimed", name="PESCH",
                    themes=["education"], tag_note="directory: 'runs schools'")
        merged = brief.merge_findings([{"findings": [older]}, {"findings": [newer]}])
        assert merged == [older, newer]
        assert org_from({**ROW, "slug": "pesch"}, merged).themes == ["education"]

    def test_the_same_page_read_again_is_still_one_fact(self):
        weak = funder(ABOUT, name="New", confidence="low")
        strong = funder(ABOUT, name="Old", confidence="high")
        assert brief.merge_findings([{"findings": [strong]}, {"findings": [weak]}]) == [strong]

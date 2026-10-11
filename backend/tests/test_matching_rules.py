"""Each match-v2 criterion from fixed profiles, and the pair's card and score."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.matching.match import match
from app.matching.rules import (
    FunderProfile,
    Identifier,
    Location,
    OrgProfile,
    PartnerLine,
    Places,
    Program,
    Themes,
    capacity,
    eligibility,
    funding_size,
    geography,
    relationship,
    theme,
)
from app.repositories.matching import Taxonomy

TODAY = date(2026, 10, 10)
PLACES = Places([
    Location(1, "country", "India", None),
    Location(2, "state", "Assam", 1),
    Location(3, "district", "Udalguri", 2),
    Location(4, "district", "Baksa", 2),
    Location(5, "state", "Bihar", 1),
])


def held(status="registered", evidence="evidenced", source="registry", valid_until=None) -> Identifier:
    return Identifier(status, "X123", True, valid_until, evidence, source)


def themes(themes=(), clauses=(), domains=()) -> Themes:
    return Themes(frozenset(themes), frozenset(clauses), frozenset(domains))


# A sub-theme as the repository expands it: its theme, its domain and its Schedule VII clauses.
SHG = themes({"sub_theme-institution-building", "theme-shg-empowerment"},
             {"csr-education-and-livelihoods", "csr-gender-equality-and-inequality"}, {"domain-livelihoods"})
LABELS = {"sub_theme-institution-building": "Institution building", "theme-shg-empowerment": "Economic empowerment of SHGs",
          "csr-education-and-livelihoods": "Education and livelihoods", "domain-livelihoods": "Livelihoods"}


def org(**kw) -> OrgProfile:
    base = {"id": 9, "name": "KABIL", "location_ids": {3}, "themes": SHG, "labels": LABELS,
            "programs": [Program(12, "Women's collectives", SHG)]}
    return OrgProfile(**(base | kw))


def funder(**kw) -> FunderProfile:
    base = {"id": 7, "name": "HDFC Bank Parivartan", "funder_type": "corporate_csr", "section_135_bound": True,
            "location_ids": {3}, "themes": SHG}
    return FunderProfile(**(base | kw))


def points(finding):
    return finding.criterion.points, finding.criterion.status


class TestTheme:
    def test_shared_tag_with_a_programme_in_it_is_full(self):
        assert points(theme(org(), funder())) == (25, "met")

    def test_shared_tag_without_a_programme_is_partial_and_says_what_to_do(self):
        f = theme(org(programs=[]), funder())
        assert points(f) == (15, "partial")
        assert "up to 10 points" in f.improve[0]

    def test_both_tagged_nothing_shared_fails_and_one_side_untagged_is_unknown(self):
        health = themes({"theme-mch-nutrition"}, {"csr-hunger-poverty-health"}, {"domain-health"})
        assert points(theme(org(), funder(themes=health))) == (0, "fail")
        assert points(theme(org(themes=Themes()), funder())) == (None, "unknown")

    def test_a_funder_theme_meets_the_org_sub_theme_under_it(self):
        f = theme(org(), funder(themes=themes({"theme-shg-empowerment"}, (), {"domain-livelihoods"})))
        assert points(f) == (25, "met")
        assert "Economic empowerment of SHGs" in f.line

    def test_a_shared_clause_alone_is_partial(self):
        # The funder's only tag is the clause its CSR filing named; the org's sub-theme links to it.
        f = theme(org(), funder(themes=themes((), {"csr-education-and-livelihoods"})))
        assert points(f) == (15, "partial")
        assert f.line == "Same Schedule VII clause: Education and livelihoods"

    def test_a_shared_domain_alone_is_weaker_still(self):
        f = theme(org(), funder(themes=themes((), (), {"domain-livelihoods"})))
        assert points(f) == (10, "partial")
        assert f.improve == []

    def test_others_is_never_a_shared_area_and_alone_is_not_recorded(self):
        others = themes((), (), {"domain-others"})
        assert points(theme(org(themes=SHG | others), funder(themes=others))) == (None, "unknown")
        gbv = themes({"sub_theme-gender-based-violence", "theme-gender-rights"}, (), {"domain-others"})
        assert points(theme(org(themes=gbv), funder(themes=others | themes({"theme-mch-nutrition"})))) == (0, "fail")

    def test_untagged_programmes_cap_a_shared_theme(self):
        f = theme(org(programs=[Program(12, "Women's collectives")]), funder())
        assert points(f) == (15, "partial")
        assert "not tagged with a theme" in f.criterion.note


class TestGeography:
    def test_district_state_and_india(self):
        assert points(geography(org(), funder(), PLACES)) == (15, "met")
        assert points(geography(org(), funder(location_ids={4}), PLACES)) == (12, "met")
        assert points(geography(org(), funder(location_ids={1}), PLACES)) == (6, "partial")

    def test_no_shared_place_fails_and_none_recorded_is_unknown(self):
        assert points(geography(org(), funder(location_ids={5}), PLACES)) == (0, "fail")
        assert points(geography(org(location_ids=set()), funder(), PLACES)) == (None, "unknown")


class TestEligibility:
    def test_a_claimed_credential_counts_and_names_its_claimant(self):
        o = org(identifiers={"12a": [held(evidence="claimed", source="website")], "80g": [held()],
                             "csr1": [held()]}, financials=[("FY2024-25", True), ("FY2023-24", True), ("FY2022-23", True)])
        f = eligibility(o, funder(), today=TODAY)
        assert points(f) == (20, "met")
        assert "claimed by website" in f.criterion.note

    def test_a_lapsed_or_missing_item_earns_nothing(self):
        o = org(identifiers={"12a": [held(valid_until=date(2025, 3, 31))], "80g": [held()]})
        f = eligibility(o, funder(), today=TODAY)
        assert points(f) == (5, "partial")  # 80G only, of 12A, 80G, audits, CSR-1
        assert "lapsed" in f.criterion.note

    def test_an_unreadable_registry_is_left_out_of_the_count(self):
        o = org(identifiers={"12a": [Identifier("check_blocked", None, True, None, None, None)], "80g": [held()]})
        f = eligibility(o, funder(funder_type="private_foundation", section_135_bound=False), today=TODAY)
        assert points(f) == (10, "partial")  # 80G of 80G and audits
        assert any("could not be read" in n for n in f.not_judged)

    def test_an_untyped_funder_does_not_count_csr1_and_says_so(self):
        o = org(identifiers={"12a": [held()], "80g": [held()]})
        f = eligibility(o, funder(funder_type=None, section_135_bound=None), today=TODAY)
        assert points(f) == (13, "partial")
        assert any("CSR Form 1" in n for n in f.not_judged)

    def test_nothing_recorded_is_unknown(self):
        assert points(eligibility(org(), funder(), today=TODAY)) == (None, "unknown")


class TestFunderSide:
    def test_relationship_is_per_funder(self):
        o = org(partner_lines=[PartnerLine(41, 7, "concluded"), PartnerLine(42, 8, "active")])
        assert points(relationship(o, funder())) == (10, "met")
        assert points(relationship(o, funder(id=99))) == (0, "fail")
        assert points(relationship(org(partner_lines=[PartnerLine(43, 7, "unconfirmed")]), funder())) == (5, "partial")

    def test_funding_size_against_income(self):
        o = org(total_income=Decimal(5_000_000))
        assert points(funding_size(o, funder(grant_size_min=Decimal(1_000_000)))) == (10, "met")
        assert points(funding_size(o, funder(grant_size_min=Decimal(8_000_000)))) == (5, "partial")
        assert points(funding_size(o, funder(grant_size_min=Decimal(20_000_000)))) == (0, "fail")
        assert points(funding_size(o, funder())) == (None, "unknown")

    def test_capacity_counts_the_last_three_completed_years(self):
        every = funder(spend=[(1, "FY2023-24"), (2, "FY2024-25"), (3, "FY2025-26")])
        assert points(capacity(every, today=TODAY)) == (5, "met")
        assert points(capacity(funder(spend=[(1, "FY2024-25")]), today=TODAY)) == (3, "partial")
        assert points(capacity(funder(spend=[(1, "FY2019-20")]), today=TODAY)) == (None, "unknown")


class TestMatch:
    def test_score_card_and_order(self):
        m = match(org(), funder(), PLACES, today=TODAY)
        assert m.criteria[0].code == "theme"
        assert m.score == {"earned": 40, "judged_max": 50, "of_100": 80}  # theme 25, geography 15, relationship 0
        assert m.tier == "strong"
        assert [r.kind for r in m.card] == ["fit", "fit", "gap"]

    def test_nothing_in_common_is_not_scored_with_one_line(self):
        m = match(org(), funder(location_ids={5}, themes=themes({"theme-mch-nutrition"})), PLACES, today=TODAY)
        assert m.score is None and m.tier == "not_scored"
        assert [r.text for r in m.card] == ["No shared place or theme recorded"]
        assert m.improve == []


class TestTaxonomyExpansion:
    """repositories.matching.Taxonomy is pure: a tag's ancestors, and its clauses."""

    TAGS = (
        {"id": 1, "slug": "domain-livelihoods", "label": "Livelihoods", "kind": "domain", "parent_id": None},
        {"id": 2, "slug": "theme-skilling", "label": "Skilling", "kind": "theme", "parent_id": 1},
        {"id": 3, "slug": "sub_theme-apprenticeships", "label": "Apprenticeships", "kind": "sub_theme", "parent_id": 2},
        {"id": 4, "slug": "sub_theme-placement", "label": "Placement", "kind": "sub_theme", "parent_id": 2},
        {"id": 5, "slug": "csr-education-and-livelihoods", "label": "ii", "kind": "csr_sector", "parent_id": None},
        {"id": 6, "slug": "csr-rural-development", "label": "x", "kind": "csr_sector", "parent_id": None},
    )
    LINKS = ({"tag_id": 3, "clause": "csr-education-and-livelihoods"}, {"tag_id": 4, "clause": "csr-rural-development"})

    def tax(self):
        return Taxonomy(list(self.TAGS), list(self.LINKS))

    def test_a_sub_theme_brings_its_theme_domain_and_own_clauses_only(self):
        assert self.tax().themes([3]) == themes({"sub_theme-apprenticeships", "theme-skilling"},
                                                {"csr-education-and-livelihoods"}, {"domain-livelihoods"})

    def test_a_theme_reaches_every_clause_its_sub_themes_do(self):
        got = self.tax().themes([2])
        assert got.clauses == {"csr-education-and-livelihoods", "csr-rural-development"}
        clause_only = funder(themes=themes((), {"csr-education-and-livelihoods"}))
        assert points(theme(org(themes=got, programs=[Program(12, "Skilling", got)]), clause_only)) == (15, "partial")

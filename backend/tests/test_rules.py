"""The matching checks, judged in code. A missing row is never a fail."""

from __future__ import annotations

from datetime import date

import pytest

from app.agent.rules import (
    FunderProfile,
    Location,
    OrgProfile,
    Places,
    Program,
    judge_org,
    judge_pair,
)

TODAY = date(2026, 10, 7)
INDIA, NE, ASSAM, BIHAR, UDALGURI, BAKSA, PATNA = 1, 3, 10, 11, 100, 101, 110
PLACES = Places([
    Location(INDIA, "country", "India", None),
    Location(NE, "region", "Northeast India", INDIA),
    Location(ASSAM, "state", "Assam", INDIA),
    Location(BIHAR, "state", "Bihar", INDIA),
    Location(UDALGURI, "district", "Udalguri", ASSAM),
    Location(BAKSA, "district", "Baksa", ASSAM),
    Location(PATNA, "district", "Patna", BIHAR),
    Location(200, "country", "Germany", None),
    Location(201, "state", "Hesse", 200),
])


def _org(**over) -> OrgProfile:
    return OrgProfile(id=9, name="KABIL", **over)


def _funder(**over) -> FunderProfile:
    base = {"id": 7, "name": "Axis Bank Foundation", "funder_type": "corporate_csr", "section_135_bound": True}
    return FunderProfile(**(base | over))


def _check(checks, code):
    return next(c for c in checks if c.code == code)


def _pair(org, funder):
    return judge_pair(org, funder, PLACES)


class TestArea:
    def test_a_shared_district_is_the_closest_level(self):
        r = _pair(_org(location_ids={UDALGURI}), _funder(location_ids={UDALGURI, ASSAM}))
        area = _check(r.checks, "area")
        assert (area.outcome, area.level) == ("met", "district")
        assert r.shared_districts == 1
        assert "[funder:7]" in area.cites

    def test_a_district_shares_its_state_with_a_funder_in_another_district(self):
        area = _check(_pair(_org(location_ids={UDALGURI}), _funder(location_ids={BAKSA})).checks, "area")
        assert (area.outcome, area.level) == ("met", "state")

    def test_pan_india(self):
        area = _check(_pair(_org(location_ids={PATNA}), _funder(location_ids={INDIA})).checks, "area")
        assert (area.outcome, area.level) == ("met", "pan_india")

    def test_no_shared_place_on_both_recorded_sides_fails(self):
        area = _check(_pair(_org(location_ids={UDALGURI}), _funder(location_ids={PATNA})).checks, "area")
        assert area.outcome == "fail"

    @pytest.mark.parametrize(("org_places", "funder_places"), [(set(), {PATNA}), ({UDALGURI}, set())])
    def test_a_side_with_no_places_is_unknown(self, org_places, funder_places):
        area = _check(_pair(_org(location_ids=org_places), _funder(location_ids=funder_places)).checks, "area")
        assert area.outcome == "unknown"

    def test_a_region_whose_members_are_not_recorded_cannot_fail(self):
        # States hang off the country, not the region, in today's data.
        area = _check(_pair(_org(location_ids={UDALGURI}), _funder(location_ids={NE})).checks, "area")
        assert area.outcome == "unknown"

    def test_a_region_whose_members_are_recorded_matches(self):
        places = Places([*PLACES.by_id.values(), Location(12, "state", "Meghalaya", NE)])
        org = _org(location_ids={12})
        area = _check(judge_pair(org, _funder(location_ids={NE}), places).checks, "area")
        assert (area.outcome, area.level) == ("met", "regional")


class TestThemeAndProgramme:
    def test_a_shared_schedule_vii_slug_is_a_shared_theme(self):
        r = _pair(_org(csr_slugs={"csr-rural-development"}), _funder(csr_slugs={"csr-rural-development"}))
        assert _check(r.checks, "theme").outcome == "met"

    def test_both_tagged_and_nothing_shared_fails(self):
        r = _pair(_org(sector_tags={"health"}), _funder(sector_tags={"education"}))
        assert _check(r.checks, "theme").outcome == "fail"

    def test_an_untagged_side_is_unknown(self):
        assert _check(_pair(_org(sector_tags={"health"}), _funder()).checks, "theme").outcome == "unknown"

    def test_no_programmes_is_unknown_whatever_theme_says(self):
        r = _pair(_org(sector_tags={"health"}), _funder(sector_tags={"education"}))
        assert _check(r.checks, "programme").outcome == "unknown"

    def test_a_programme_in_a_shared_theme_is_met(self):
        prog = Program(1, "Farm schools", None, None, frozenset({"agriculture"}))
        r = _pair(_org(sector_tags={"agriculture"}, programs=[prog]), _funder(sector_tags={"agriculture"}))
        assert _check(r.checks, "programme").outcome == "met"

    def test_with_programmes_recorded_a_failed_theme_fails_programme(self):
        prog = Program(1, "Clinics", None, None, frozenset({"health"}))
        r = _pair(_org(sector_tags={"health"}, programs=[prog]), _funder(sector_tags={"education"}))
        assert _check(r.checks, "programme").outcome == "fail"

    def test_untagged_programmes_are_unknown_not_fail(self):
        prog = Program(1, "Clinics", None, None, frozenset())
        r = _pair(_org(sector_tags={"health"}, programs=[prog]), _funder(sector_tags={"health"}))
        assert _check(r.checks, "programme").outcome == "unknown"


class TestCredentials:
    def test_a_current_identifier_is_met_and_cites_the_org(self):
        c = _check(judge_org(_org(identifiers={"12a": [True]}), today=TODAY), "reg_12a")
        assert (c.outcome, c.cites) == ("met", ["[org:9]"])

    def test_no_row_is_unknown_never_fail(self):
        checks = judge_org(_org(), today=TODAY)
        assert all(c.outcome == "unknown" for c in checks)

    def test_a_cancellation_fails(self):
        org = _org(identifiers={"80g": [True]}, events={"80g": ("cancelled", None)})
        assert _check(judge_org(org, today=TODAY), "reg_80g").outcome == "fail"

    def test_a_lapsed_validity_fails(self):
        org = _org(identifiers={"80g": [True]}, events={"80g": ("renewed", date(2025, 3, 31))})
        assert _check(judge_org(org, today=TODAY), "reg_80g").outcome == "fail"

    def test_searched_and_not_found_says_so(self):
        c = _check(judge_org(_org(events={"csr1": ("not_found", None)}), today=TODAY), "csr_1")
        assert (c.outcome, c.basis) == ("unknown", "searched_not_found")


class TestCountsBelowABarAreNotFails:
    def test_one_concluded_grant_is_unknown(self):
        c = _check(judge_org(_org(grants=[(4, "concluded"), (5, "active")]), today=TODAY), "projects_3")
        assert c.outcome == "unknown"
        assert "1 of 3" in c.note

    def test_three_concluded_grants_are_met_and_cite_each(self):
        c = _check(judge_org(_org(grants=[(1, "concluded"), (2, "concluded"), (3, "concluded")]), today=TODAY),
                   "projects_3")
        assert c.outcome == "met"
        assert c.cites == ["[grant:1]", "[grant:2]", "[grant:3]"]

    def test_two_office_bearers_is_unknown(self):
        assert _check(judge_org(_org(office_bearers=2), today=TODAY), "board").outcome == "unknown"

    def test_a_recent_year_recorded_unaudited_fails(self):
        org = _org(financials=[("2024-25", False), ("2023-24", True)])
        assert _check(judge_org(org, today=TODAY), "audits_3y").outcome == "fail"

    def test_three_audit_documents_are_met(self):
        org = _org(doc_types=["audited_financials", "financial_statements", "financial_statement"])
        c = _check(judge_org(org, today=TODAY), "audits_3y")
        assert (c.outcome, c.basis) == ("met", "on_file")


class TestTheFundersSide:
    def test_every_eligibility_row_is_a_bar_for_review(self):
        r = _pair(_org(), _funder(bars=[(4, "registered 3+ years"), (5, "works in Assam")]))
        bars = [c for c in r.checks if c.code == "funder_bar"]
        assert [b.outcome for b in bars] == ["unknown", "unknown"]
        assert "needs review" in bars[0].note

    @pytest.mark.parametrize(("registered", "foreign"), [({UDALGURI}, False), ({201}, True), (set(), None)])
    def test_foreign_funder_follows_the_registered_country(self, registered, foreign):
        assert _pair(_org(), _funder(registered_ids=registered)).foreign_funder is foreign


def test_the_same_organisation_gets_the_same_checks_every_time():
    org = _org(identifiers={"12a": [True]}, office_bearers=1)
    assert judge_org(org, today=TODAY) == judge_org(org, today=TODAY)

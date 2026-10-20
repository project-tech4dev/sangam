"""Source labels a finding must carry, and the taxonomy and geography look-ups a write resolves through."""

from __future__ import annotations

import pytest

from app.ingest import geography, source_guards, taxonomy
from app.ingest.writer import GATE, Gate
from tests.cov_ingest_fakes import ScriptConn

PINNED = ("https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/"
          "414cd6968765bcfff758632797dcbb8d00363ab2/cso/arpan.md")
MIRROR = "https://github.com/project-tech4dev/org-grant-intelligence/blob/main/cso/arpan.md"
GIVE = "https://give.do/discover/arpan"


class TestLabels:
    @pytest.mark.parametrize(("url", "label"), [
        (PINNED, "prior_research"),
        (MIRROR, "prior_research"),
        ("https://cdn.jsdelivr.net/gh/project-tech4dev%2Forg-grant-intelligence/a.md", "prior_research"),
        (GIVE, "aggregator"),
        ("https://www.guidestarindia.org/Search", "aggregator"),
        ("https://example.org/csr", None),
    ])
    def test_labelled_by(self, url, label):
        found = source_guards.labelled_by(url)
        assert (found and found[0]) == label

    def test_private_sources(self):
        assert source_guards.is_private_source("https://staff-sources.sangam.invalid/1")
        assert source_guards.is_private_source("https://sangam.invalid/1")
        assert not source_guards.is_private_source(None)


def finding(url, **over) -> dict:
    return {"concept": "program", "source_url": url, **over}


TIERED = frozenset({"source_type", "evidence_tier"})


class TestProblems:
    def test_prior_research_must_cite_the_repository(self):
        [why] = source_guards.problems("program", finding("https://example.org", source_type="prior_research"),
                                       TIERED, "org", at="save")
        assert "prior_research cites the research repository" in why

    def test_an_aggregator_value_is_claimed(self):
        [why] = source_guards.problems("program", finding(GIVE, source_type="aggregator", evidence_tier="evidenced"),
                                       TIERED, "org", at="save")
        assert "set source_type='aggregator' and evidence_tier='claimed'" in why
        assert source_guards.problems("program", finding(GIVE, source_type="aggregator", evidence_tier="claimed"),
                                      TIERED, "org", at="save") == []

    def test_an_untiered_table_holds_it_at_promote(self):
        [why] = source_guards.problems("rfp", finding(GIVE), frozenset(), "funder", at="promote")
        assert "its table cannot mark a value claimed" in why
        assert source_guards.problems("rfp", finding(GIVE), frozenset(), "funder", at="save") == []

    def test_hold_at_promote_splits_kept_and_held(self):
        ok = {"concept": "rfp", "source_url": "https://example.org"}
        held_one = {"concept": "rfp", "source_url": GIVE}
        unknown = {"concept": "nonsense", "source_url": GIVE}
        kept, held = source_guards.hold_at_promote([ok, held_one, unknown], "funder")
        assert kept == [ok] and len(held) == 2


class TestTaxonomy:
    def test_clause_for(self):
        assert taxonomy.clause_for(None) is None
        assert taxonomy.clause_for("Skill development for youth") == "csr-education-and-livelihoods"
        assert taxonomy.clause_for("misc") is None

    async def test_resolve_csr_sector(self):
        conn = ScriptConn([("FROM tags", {"id": 12})])
        assert await taxonomy.resolve_csr_sector(conn, "school books") == 12
        assert await taxonomy.resolve_csr_sector(ScriptConn(), "school books") is None
        assert await taxonomy.resolve_csr_sector(conn, "misc") is None

    async def test_no_domain_is_nothing(self):
        assert await taxonomy.resolve_classification(ScriptConn(), None, "x") == (None, None, [])

    async def test_a_bad_domain_holds_the_line(self):
        _, _, [why] = await taxonomy.resolve_classification(ScriptConn(), "sports", None)
        assert "is not one of livelihoods" in why

    async def test_an_unseeded_domain_says_how_to_seed(self):
        _, _, [why] = await taxonomy.resolve_classification(ScriptConn(), "health", None)
        assert "make taxonomy-seed" in why

    async def test_a_domain_alone(self):
        conn = ScriptConn([("kind = 'domain'", {"id": 2})])
        assert await taxonomy.resolve_classification(conn, "health", "") == (2, None, [])

    @pytest.mark.parametrize(("themes", "expect", "phrase"), [
        ([{"id": 9, "domain": "health"}], (2, 9), None),
        ([], (2, None), "is not in the taxonomy"),
        ([{"id": 9, "domain": "health"}, {"id": 10, "domain": "health"}], (2, None), "is ambiguous"),
        ([{"id": 9, "domain": "education"}], (2, None), "belongs to 'education'"),
    ])
    async def test_a_theme(self, themes, expect, phrase):
        conn = ScriptConn([("kind = 'domain'", {"id": 2}), ("'sub_theme'", themes)])
        domain_id, theme_id, reasons = await taxonomy.resolve_classification(conn, "health", "nutrition")
        assert (domain_id, theme_id) == expect
        assert (reasons == []) if phrase is None else phrase in reasons[0]


class TestGeography:
    def test_canonical_state(self):
        assert geography.canonical_state("  assam STATE ") == "Assam"
        assert geography.canonical_state("Atlantis") is None

    def test_district_key_and_qualifiers(self):
        assert geography.district_key("Ri-Bhoi District") == "ribhoi"
        assert geography.qualifiers("Bangalore Rural") == frozenset({"rural"})

    async def test_no_state(self):
        assert await geography.resolve_location(ScriptConn(), None) == (None, "no place given")
        _, why = await geography.resolve_location(ScriptConn(), None, "Bishnupur")
        assert "has no state" in why

    async def test_an_unknown_state_is_not_created(self):
        conn = ScriptConn()
        _, why = await geography.resolve_location(conn, "Atlantis")
        assert "not one of India's 28 states" in why and not conn.calls

    async def test_a_known_state(self):
        conn = ScriptConn([("kind = %s", {"id": 3})])
        assert await geography.resolve_location(conn, "Assam") == (3, None)

    async def test_a_missing_state_is_added_but_never_in_a_plan(self):
        conn = ScriptConn([("SELECT id FROM locations", None), ("INSERT INTO locations", {"id": 40})])
        assert await geography.resolve_location(conn, "Assam") == (40, None)
        token = GATE.set(Gate(plan=True))
        try:
            assert await geography.resolve_location(ScriptConn(), "Assam") == (-1, None)
        finally:
            GATE.reset(token)

    async def test_a_concurrent_insert_is_found_again(self):
        conn = ScriptConn([("SELECT id FROM locations", (None, {"id": 41})), ("INSERT INTO locations", None)])
        assert await geography._ensure(conn, "country", "India", None) == 41

    async def test_a_district_by_name(self):
        conn = ScriptConn([("kind = 'district' AND parent_id = %s AND", {"id": 77}), ("kind = %s", {"id": 3})])
        assert await geography.resolve_location(conn, "Assam", "Kamrup Metro") == (77, None)

    async def test_a_clearly_closest_district(self):
        conn = ScriptConn([("AS score", [{"id": 78, "name": "KAMRUP METROPOLITAN", "score": 0.7},
                                         {"id": 79, "name": "KAMRUP", "score": 0.3}]),
                           ("kind = %s", {"id": 3})])
        district_id, note = await geography.resolve_location(conn, "Assam", "Kamrup Metro")
        assert district_id == 78 and "was read as KAMRUP METROPOLITAN" in note

    async def test_no_clear_district_lists_the_options(self):
        conn = ScriptConn([("AS score", [{"id": 78, "name": "KAMRUP", "score": 0.5},
                                         {"id": 79, "name": "KAMRUP METRO", "score": 0.45}]),
                           ("kind = %s", {"id": 3})])
        district_id, why = await geography.resolve_location(conn, "Assam", "Kamrup M")
        assert district_id is None and "of: KAMRUP (0.50), KAMRUP METRO (0.45)" in why

    async def test_no_district_at_all(self):
        conn = ScriptConn([("kind = %s", {"id": 3})])
        district_id, why = await geography.resolve_location(conn, "Assam", "Nowhere")
        assert district_id is None and "a person picks one, or adds" in why

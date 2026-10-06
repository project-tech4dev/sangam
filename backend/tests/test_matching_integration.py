"""The matching engine against the compose Postgres; every test rolls back."""

from __future__ import annotations

import copy
from unittest.mock import patch

import psycopg
import pytest

from app.matching import __main__ as cli
from app.matching import evidence, registry, service
from app.matching.config import CriteriaError, load_yaml
from app.matching.models import Ambiguous, Resolved
from app.matching.themes import backfill_programme_themes

pytestmark = pytest.mark.integration


def raw_criteria(version=1, set_name="test-set"):
    raw = copy.deepcopy(load_yaml()[1])
    raw["set"], raw["version"] = set_name, version
    return raw


class TestRegistry:
    async def test_load_draft_records_hash_and_sha(self, db):
        v = await registry.load_draft(db, raw_criteria(), git_sha="abc123")
        rows = await registry.list_sets(db, "test-set")
        assert (v, rows[0]["status"], rows[0]["git_sha"]) == (1, "draft", "abc123")
        assert len(rows[0]["content_hash"]) == 64

    async def test_loading_the_same_content_twice_does_not_duplicate(self, db):
        await registry.load_draft(db, raw_criteria())
        await registry.load_draft(db, raw_criteria())
        assert len(await registry.list_sets(db, "test-set")) == 1

    async def test_same_version_different_content_is_refused(self, db):
        await registry.load_draft(db, raw_criteria())
        changed = raw_criteria()
        changed["checks"][0]["label"] = "something else"
        with pytest.raises(CriteriaError, match="bump"):
            await registry.load_draft(db, changed)

    async def test_no_active_version_raises(self, db):
        await registry.load_draft(db, raw_criteria())
        with pytest.raises(registry.NoActiveCriteria):
            await registry.get(db, "test-set")

    async def test_activate_retires_the_previous_and_rollback_reactivates(self, db):
        await registry.load_draft(db, raw_criteria(1))
        await registry.load_draft(db, raw_criteria(2))
        await registry.activate(db, "test-set", 1)
        await registry.activate(db, "test-set", 2)
        status = {r["version"]: r["status"] for r in await registry.list_sets(db, "test-set")}
        assert status == {1: "retired", 2: "active"}
        assert (await registry.get(db, "test-set")).version == 2
        await registry.activate(db, "test-set", 1)
        assert (await registry.get(db, "test-set")).version == 1

    async def test_a_specific_version_can_be_read_whatever_its_status(self, db):
        await registry.load_draft(db, raw_criteria(1))
        loaded = await registry.get(db, "test-set", 1)
        assert (loaded.version, loaded.status) == (1, "draft")

    async def test_the_index_allows_one_active_row(self, db):
        await registry.load_draft(db, raw_criteria(1))
        await registry.load_draft(db, raw_criteria(2))
        await db.execute("UPDATE criteria_sets SET status = 'active' WHERE set_name = 'test-set' AND version = 1")
        with pytest.raises(psycopg.errors.UniqueViolation):
            await db.execute("UPDATE criteria_sets SET status = 'active' WHERE set_name = 'test-set' AND version = 2")


class TestProgrammeThemes:
    async def test_tags_a_matching_programme_once(self, db):
        f = (await (await db.execute(
            "INSERT INTO funders (slug, name) VALUES ('t-funder', 'T Funder') RETURNING id")).fetchone())["id"]
        p = (await (await db.execute(
            "INSERT INTO programs (funder_id, name, description) VALUES (%s, 'Parivartan', "
            "'sustainable livelihoods for rural women artisans') RETURNING id", (f,))).fetchone())["id"]
        assert await backfill_programme_themes(db) >= 1
        tags = await (await db.execute(
            "SELECT t.slug, pt.is_inferred, pt.tagged_by FROM program_tags pt JOIN tags t ON t.id = pt.tag_id "
            "WHERE pt.program_id = %s", (p,))).fetchall()
        assert tags == [{"slug": "csr-education-and-livelihoods", "is_inferred": True,
                         "tagged_by": "taxonomy.clause_for"}]
        assert await backfill_programme_themes(db) == 0


# --- evidence resolver ----------------------------------------------------------------------

async def one(db, sql, params=()):
    return (await (await db.execute(sql + " RETURNING id", params)).fetchone())["id"]


async def place(db, kind, name, parent):
    return await one(db, "INSERT INTO locations (kind, name, parent_id) VALUES (%s, %s, %s)", (kind, name, parent))


@pytest.fixture
async def world(db):
    """A synthetic state with two districts, a region, two clauses, and an org in one district."""
    india = (await (await db.execute("SELECT id FROM locations WHERE kind = 'country'")).fetchone())["id"]
    w = {"india": india}
    w["state"] = await place(db, "state", "Tstate", india)
    w["other_state"] = await place(db, "state", "Ostate", india)
    w["d1"] = await place(db, "district", "Tdist1", w["state"])
    w["d2"] = await place(db, "district", "Tdist2", w["state"])
    w["region"] = await place(db, "region", "Tregion", india)
    w["csr_a"] = await one(db, "INSERT INTO tags (slug, label, kind) VALUES ('csr-test-a', 'Test A', 'csr_sector')")
    w["csr_b"] = await one(db, "INSERT INTO tags (slug, label, kind) VALUES ('csr-test-b', 'Test B', 'csr_sector')")
    w["sector_a"] = await one(db, "INSERT INTO tags (slug, label, kind, meta) VALUES "
                                  "('test-sector-a', 'Sector A', 'sector', '{\"maps_to\": \"csr-test-a\"}')")
    w["sector_null"] = await one(db, "INSERT INTO tags (slug, label, kind, meta) VALUES "
                                     "('test-sector-n', 'Sector N', 'sector', '{\"maps_to\": null}')")
    w["org"] = await one(db, "INSERT INTO orgs (slug, name) VALUES ('t-org', 'T Org')")
    await db.execute("INSERT INTO org_locations (org_id, location_id, role) VALUES (%s, %s, 'operates')",
                     (w["org"], w["d1"]))
    await db.execute("INSERT INTO org_tags (org_id, tag_id, role) VALUES (%s, %s, 'primary'), (%s, %s, 'secondary')",
                     (w["org"], w["sector_a"], w["org"], w["sector_null"]))
    return w


async def funder(db, slug, funder_type=None):
    return await one(db, "INSERT INTO funders (slug, name, funder_type) VALUES (%s, %s, %s)",
                     (slug, slug.upper(), funder_type))


async def load(db, world, kinds=evidence.ORG_KINDS):
    return await evidence.load_org(db, world["org"], kinds)


class TestLoadOrg:
    async def test_a_district_also_counts_as_its_state(self, db, world):
        org = await load(db, world)
        assert (org.districts, org.states) == ({world["d1"]: "Tdist1"}, {world["state"]: "Tstate"})

    async def test_clauses_come_through_maps_to_and_skip_a_null_mapping(self, db, world):
        await db.execute("INSERT INTO org_tags (org_id, tag_id, role) VALUES (%s, %s, 'secondary')",
                         (world["org"], world["csr_b"]))
        assert (await load(db, world)).clauses == {"csr-test-a": "Test A", "csr-test-b": "Test B"}

    async def test_only_current_identifiers_are_read(self, db, world):
        await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, is_current) VALUES "
                         "(%s, '12a', 'AAA', true), (%s, '80g', 'OLD', false)", (world["org"], world["org"]))
        assert {k: f.value for k, f in (await load(db, world)).identifiers.items()} == {"12a": "AAA"}

    async def test_latest_event_wins_but_check_blocked_is_skipped(self, db, world):
        await db.execute(
            "INSERT INTO credential_events (org_id, credential, event, event_date) VALUES "
            "(%s, '12a', 'registered', '2020-01-01'), (%s, '12a', 'check_blocked', '2025-01-01'), "
            "(%s, '80g', 'registered', '2020-01-01'), (%s, '80g', 'cancelled', '2024-06-01')",
            (world["org"],) * 4)
        events = (await load(db, world)).credential_events
        assert {k: (f.value, f.as_of) for k, f in events.items()} == {
            "12a": ("registered", "2020-01-01"), "80g": ("cancelled", "2024-06-01")}

    async def test_financials_carry_the_audit_flag_per_year(self, db, world):
        await db.execute("INSERT INTO org_financials (org_id, fiscal_year, total_income, is_audited) VALUES "
                         "(%s, 'FY2022-23', 100, true), (%s, 'FY2023-24', 200, NULL)", (world["org"], world["org"]))
        fin = (await load(db, world)).financials
        assert [(f.key, f.value["is_audited"]) for f in fin] == [("FY2022-23", True), ("FY2023-24", None)]

    async def test_board_is_office_bearers_only(self, db, world):
        await db.execute("INSERT INTO contacts (org_id, name, kind, role) VALUES "
                         "(%s, 'A', 'office_bearer', 'President'), (%s, 'B', 'programme', NULL)",
                         (world["org"], world["org"]))
        assert [f.key for f in (await load(db, world)).board] == ["A"]

    async def test_documents_split_vault_from_research_and_skip_requested(self, db, world):
        uid = (await (await db.execute("SELECT id FROM users LIMIT 1")).fetchone())["id"]
        await db.execute(
            "INSERT INTO documents (org_id, doc_type, status, uploaded_by) VALUES "
            "(%s, 'csr1_certificate', 'read', %s), (%s, 'csr1_certificate', 'read', NULL), "
            "(%s, 'audited_financials', 'requested', NULL)",
            (world["org"], uid, world["org"], world["org"]))
        docs = (await load(db, world)).documents
        assert sorted(d.vault for d in docs["csr1_certificate"]) == [False, True]
        assert "audited_financials" not in docs

    async def test_projects_come_from_grants_and_org_programmes(self, db, world):
        f = await funder(db, "t-proj-funder")
        prog = await one(db, "INSERT INTO programs (funder_id, name) VALUES (%s, 'Fprog')", (f,))
        await db.execute("INSERT INTO program_tags (program_id, tag_id, role) VALUES (%s, %s, 'primary')",
                         (prog, world["csr_a"]))
        g = await one(db, "INSERT INTO grants (org_id, funder_id, program_id, title, status, amount, start_date, "
                          "end_date, outcomes) VALUES (%s, %s, %s, 'G', 'concluded', 500000, '2020-04-01', "
                          "'2021-03-31', '{\"reached\": 10}')", (world["org"], f, prog))
        await db.execute("INSERT INTO programs (org_id, name) VALUES (%s, 'Own work')", (world["org"],))
        by_source = {p.source: p for p in (await load(db, world)).projects}
        assert by_source["grant"].cite == f"[grant:{g}]"
        assert by_source["grant"].missing(("funder", "amount", "theme", "duration", "results")) == []
        assert by_source["programme"].missing(("funder", "amount")) == ["funder", "amount"]

    async def test_not_found_comes_from_resolved_research(self, db, world):
        await db.execute(
            "INSERT INTO entity_research (entity_name, entity_kind, slug, status, summary, not_found, "
            "resolved_org_id, researched_on) VALUES ('T', 'org', 't-res', 'complete', 's', "
            "ARRAY['12A registration'], %s, '2026-10-01')", (world["org"],))
        nf = (await load(db, world)).not_found
        assert [(c, d.isoformat()) for c, d in nf] == [("12A registration", "2026-10-01")]

    async def test_only_the_kinds_read_are_loaded(self, db, world):
        await db.execute("INSERT INTO org_identifiers (org_id, id_type, id_value) VALUES (%s, '12a', 'AAA')",
                         (world["org"],))
        org = await load(db, world, {"org.places"})
        assert org.districts and not org.identifiers and not org.clauses

    async def test_an_unknown_org_raises(self, db):
        with pytest.raises(LookupError):
            await evidence.load_org(db, -1, evidence.ORG_KINDS)


class TestLoadFit:
    async def fit(self, db, world, funder_id):
        return (await evidence.load_fit(db, await load(db, world)))[funder_id]

    async def test_district_match_and_the_funder_ref(self, db, world):
        f = await funder(db, "t-f-dist", "corporate_csr")
        await db.execute("INSERT INTO funder_locations (funder_id, location_id, role) VALUES (%s, %s, 'funds')",
                         (f, world["d1"]))
        ev = await self.fit(db, world, f)
        assert ev.funder.funder_type == "corporate_csr"
        assert (ev.fit.shared_districts, ev.fit.shared_states, ev.fit.stated_places) == (
            ("Tdist1",), ("Tstate",), 1)

    async def test_a_funder_district_in_the_same_state_shares_the_state(self, db, world):
        f = await funder(db, "t-f-sib")
        await db.execute("INSERT INTO funder_footprints (funder_id, location_id, fiscal_year) VALUES "
                         "(%s, %s, 'FY2023-24')", (f, world["d2"]))
        ev = await self.fit(db, world, f)
        assert (ev.fit.shared_districts, ev.fit.shared_states) == ((), ("Tstate",))
        assert (ev.fit.stated_places, ev.fit.observed_places) == (0, 1)

    async def test_country_is_pan_india_and_region_is_flagged(self, db, world):
        f = await funder(db, "t-f-wide")
        await db.execute("INSERT INTO funder_locations (funder_id, location_id, role) VALUES "
                         "(%s, %s, 'funds'), (%s, %s, 'priority')", (f, world["india"], f, world["region"]))
        ev = await self.fit(db, world, f)
        assert (ev.fit.pan_india, ev.fit.regions, ev.fit.stated_places) == (True, ("Tregion",), 2)

    async def test_the_registered_office_is_not_a_stated_place(self, db, world):
        f = await funder(db, "t-f-reg")
        await db.execute("INSERT INTO funder_locations (funder_id, location_id, role) VALUES "
                         "(%s, %s, 'registered'), (%s, %s, 'funds')", (f, world["d1"], f, world["other_state"]))
        ev = await self.fit(db, world, f)
        assert (ev.fit.shared_districts, ev.fit.shared_states, ev.fit.stated_places) == ((), (), 1)

    async def test_an_expired_stated_place_does_not_count(self, db, world):
        f = await funder(db, "t-f-old")
        await db.execute("INSERT INTO funder_locations (funder_id, location_id, role, valid_to) VALUES "
                         "(%s, %s, 'funds', '2020-01-01')", (f, world["d1"]))
        assert (await self.fit(db, world, f)).fit == evidence.PairFit()

    async def test_themes_and_programmes_are_intersected_with_the_org(self, db, world):
        f = await funder(db, "t-f-theme")
        await db.execute("INSERT INTO funder_tags (funder_id, tag_id, role) VALUES (%s, %s, 'primary'), "
                         "(%s, %s, 'secondary')", (f, world["sector_a"], f, world["csr_b"]))
        p1 = await one(db, "INSERT INTO programs (funder_id, name) VALUES (%s, 'Zeta')", (f,))
        p2 = await one(db, "INSERT INTO programs (funder_id, name) VALUES (%s, 'Alpha')", (f,))
        p3 = await one(db, "INSERT INTO programs (funder_id, name) VALUES (%s, 'Other')", (f,))
        await db.execute("INSERT INTO program_tags (program_id, tag_id, role) VALUES (%s, %s, 'primary'), "
                         "(%s, %s, 'primary'), (%s, %s, 'primary')",
                         (p1, world["csr_a"], p2, world["csr_a"], p3, world["csr_b"]))
        ev = await self.fit(db, world, f)
        assert (ev.fit.tag_clauses, ev.fit.shared_tag_clauses) == (("csr-test-a", "csr-test-b"), ("csr-test-a",))
        assert (ev.fit.tagged_programmes, ev.fit.shared_programmes) == (3, ("Alpha", "Zeta"))

    async def test_a_funder_with_nothing_recorded_gets_an_empty_fit(self, db, world):
        f = await funder(db, "t-f-empty")
        assert (await self.fit(db, world, f)).fit == evidence.PairFit()

    async def test_enrich_refuses_a_kind_it_cannot_load(self, db):
        with pytest.raises(ValueError, match="funder.nope"):
            await evidence.enrich_funders(db, {}, {"funder.nope"})


class TestQueryCount:
    async def test_stages_one_and_two_stay_within_six_queries_for_200_funders(self, db, world):
        await db.execute("INSERT INTO funders (slug, name) SELECT 't-bulk-' || i, 'Bulk ' || i "
                         "FROM generate_series(1, 200) i")
        await db.execute("INSERT INTO funder_footprints (funder_id, location_id, fiscal_year) "
                         "SELECT id, %s, 'FY2023-24' FROM funders WHERE slug LIKE 't-bulk-%%'", (world["d1"],))
        org = await load(db, world)
        with patch.object(db, "execute", wraps=db.execute) as spy:
            funders = await evidence.load_fit(db, org)
            await evidence.enrich_funders(db, funders, evidence.FUNDER_KINDS)
        assert spy.call_count <= 6
        assert sum(1 for f in funders.values() if f.fit.shared_districts == ("Tdist1",)) == 200


# --- service and CLI ------------------------------------------------------------------------

@pytest.fixture
async def active(db):
    """The repo's criteria file, active inside this test's transaction."""
    raw = load_yaml()[1]
    await registry.load_draft(db, raw)
    await registry.activate(db, raw["set"], raw["version"])
    return raw["version"]


async def place_funder(db, world, slug):
    f = await funder(db, slug)
    await db.execute("INSERT INTO funder_locations (funder_id, location_id, role) VALUES (%s, %s, 'funds')",
                     (f, world["d1"]))
    return f


class TestService:
    async def test_a_district_match_ranks_first_and_an_empty_funder_is_not_enough_recorded(
            self, db, world, active):
        near, empty = await place_funder(db, world, "t-s-near"), await funder(db, "t-s-empty")
        sl = await service.shortlist(db, world["org"], limit=500)
        assert sl.criteria_version == active
        assert sl.ranked[0].funder.id == near
        assert empty in [f.id for f in sl.not_enough_recorded]
        assert empty not in [a.funder.id for a in sl.ranked + sl.did_not_pass]
        assert sl.total_funders == len(sl.ranked) + len(sl.not_enough_recorded) + len(sl.did_not_pass)

    async def test_an_org_with_nothing_recorded_fails_no_one_and_ranks_no_one(self, db, active):
        bare = await one(db, "INSERT INTO orgs (slug, name) VALUES ('t-bare', 'T Bare')")
        sl = await service.shortlist(db, bare, limit=500)
        assert (sl.ranked, sl.did_not_pass) == ([], [])
        assert len(sl.not_enough_recorded) == sl.total_funders

    async def test_paging_slices_the_ranked_list_in_rank_order(self, db, world, active):
        await place_funder(db, world, "t-s-p1")
        await place_funder(db, world, "t-s-p2")
        everything = (await service.shortlist(db, world["org"], limit=500)).ranked
        page = await service.shortlist(db, world["org"], limit=1, offset=1)
        assert [a.funder.id for a in page.ranked] == [everything[1].funder.id]

    async def test_a_tie_breaks_on_funder_id(self, db, world, active):
        a, b = await place_funder(db, world, "t-s-tie-a"), await place_funder(db, world, "t-s-tie-b")
        ids = [x.funder.id for x in (await service.shortlist(db, world["org"], limit=500)).ranked]
        assert ids.index(a) < ids.index(b)

    async def test_assess_many_keeps_the_order_given(self, db, world, active):
        a, b = await place_funder(db, world, "t-s-am-a"), await funder(db, "t-s-am-b")
        got = await service.assess_many(db, world["org"], [b, a])
        assert [x.funder.id for x in got] == [b, a]

    async def test_assessing_a_missing_funder_raises(self, db, world, active):
        with pytest.raises(LookupError):
            await service.assess(db, world["org"], -1)

    async def test_no_active_criteria_is_a_clear_error(self, db, world):
        await db.execute("UPDATE criteria_sets SET status = 'retired' WHERE status = 'active'")
        with pytest.raises(registry.NoActiveCriteria):
            await service.shortlist(db, world["org"])


class TestResolve:
    async def test_slug_id_and_name_resolve_to_one(self, db, world):
        for text in ("t-org", str(world["org"]), "T ORG"):
            got = await service.resolve(db, "org", text)
            assert isinstance(got, Resolved) and got.id == world["org"], text

    async def test_a_partial_name_shared_by_two_is_ambiguous(self, db):
        await db.execute("INSERT INTO funders (slug, name) VALUES ('t-zq-one', 'Zqx Alpha Trust'), "
                         "('t-zq-two', 'Zqx Alpha Society')")
        got = await service.resolve(db, "funder", "zqx alpha")
        assert isinstance(got, Ambiguous)
        assert sorted(c.slug for c in got.candidates) == ["t-zq-one", "t-zq-two"]

    async def test_nothing_close_gives_no_candidates(self, db):
        got = await service.resolve(db, "funder", "qqqqqqqqqqqqqq")
        assert isinstance(got, Ambiguous) and got.candidates == []


class TestCli:
    async def test_match_prints_the_criteria_version_and_the_top_funder(self, db, world, active, capsys):
        await place_funder(db, world, "t-cli-near")
        assert await cli.run(["match", "--org", "t-org"], db) == 0
        out = capsys.readouterr().out
        assert f"criteria v{active}" in out and "T-CLI-NEAR" in out

    async def test_an_unresolved_org_exits_nonzero(self, db, active, capsys):
        assert await cli.run(["match", "--org", "qqqqqqqqqqqqqq"], db) == 1

    async def test_explain_lists_every_check(self, db, world, active, capsys):
        await place_funder(db, world, "t-cli-ex")
        assert await cli.run(["explain", "--org", "t-org", "--funder", "t-cli-ex"], db) == 0
        out = capsys.readouterr().out
        assert "area" in out and "met" in out and "not_applicable" in out

"""What the catalog holds, what research would change, and the two steps that write to it."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from psycopg.errors import UniqueViolation

from app.core.security import CallerScope, chat_user_id
from app.ingest.matcher import Match
from app.ingest.tools import catalog_tools
from app.ingest.writer import UNWRITTEN
from tests.cov_ingest_fakes import BrokenPool, ScriptPool, running_as
from tests.test_import_roles import ARPAN_STEWARD, MEMBER, STAFF

PUBLIC = "https://example.org/csr"
STAFF_URL = "https://staff-sources.sangam.invalid/12"
VAULT_URL = "https://org-vault.sangam.invalid/12"


@pytest.fixture
def pool(monkeypatch):
    p = ScriptPool()
    monkeypatch.setattr(catalog_tools, "get_pool", lambda: p)
    return p


def resolves(monkeypatch, match: Match):
    async def resolve(conn, name):
        return match
    monkeypatch.setattr(catalog_tools, "resolve_funder", resolve)
    monkeypatch.setattr(catalog_tools, "resolve_org", resolve)


ACME = {"id": 4, "name": "Acme Foundation", "slug": "acme", "registry_status": None, "website": "https://acme.org"}


class TestDossier:
    async def test_an_unknown_kind_is_refused(self):
        out = await catalog_tools.funder_dossier.ainvoke({"name": "Acme", "entity_kind": "unknown"})
        assert out.startswith("REFUSED: entity_kind must be 'funder' or 'org'")

    async def test_no_match_lists_close_names_as_not_the_same(self, monkeypatch, pool):
        pool.conn.on("FROM funders", [{**ACME, "id": 9, "name": "SBI Foundation"}])
        resolves(monkeypatch, Match("new"))
        out = await catalog_tools.funder_dossier.ainvoke({"name": "Infosys Foundation"})
        assert out.startswith("No funder in the catalog matches 'Infosys Foundation'")
        assert "SBI Foundation [funder:9]" in out

    async def test_a_match_prints_its_head_and_each_section(self, monkeypatch, pool):
        pool.conn.on("FROM funders", [ACME, {**ACME, "id": 5, "name": "Acme Trust"}])
        pool.conn.on("FROM funder_csr_years", [{"id": i, "fiscal_year": f"FY{i}", "total_spent": i, "x": None}
                                               for i in range(22)])
        resolves(monkeypatch, Match("exact", 4))
        out = await catalog_tools.funder_dossier.ainvoke({"name": "Acme"})
        assert out.startswith("funders [funder:4] Acme Foundation (acme)")
        assert "registry_status=not recorded website=https://acme.org" in out
        assert "other rows with a similar name: Acme Trust [funder:5]" in out
        assert "funder_csr_years (amounts in INR) (22):" in out and "… and 2 more" in out
        assert "\ncontacts: NOT RECORDED" in out

    async def test_a_resolved_match_outside_the_similar_rows_is_fetched(self, monkeypatch, pool):
        pool.conn.on("FROM orgs WHERE id = %s", {**ACME, "id": 7, "name": "Arpan", "slug": "arpan"})
        resolves(monkeypatch, Match("identifier", 7))
        out = await catalog_tools.funder_dossier.ainvoke({"name": "Arpan", "entity_kind": "org"})
        assert out.startswith("orgs [org:7] Arpan (arpan)") and "org_identifiers" in out

    async def test_a_failure_is_returned(self, monkeypatch):
        monkeypatch.setattr(catalog_tools, "get_pool", lambda: BrokenPool())
        assert await catalog_tools.funder_dossier.ainvoke({"name": "Acme"}) == "funder_dossier failed: database down"


class TestResearchGoals:
    async def test_unknown_kind(self):
        out = await catalog_tools.research_goals.ainvoke({"name": "Acme", "entity_kind": "unknown"})
        assert out.startswith("REFUSED")

    async def test_a_new_funder(self, pool):
        out = await catalog_tools.research_goals.ainvoke({"name": "Acme", "entity_kind": "funder",
                                                          "years": "FY2024-25"})
        assert "Years to cover: FY2024-25." in out and "Nothing in the catalog matches 'Acme'" in out
        assert "csr_year -> funder_csr_years: NOT RECORDED" in out and "keys:" in out

    async def test_a_held_org_shows_counts_and_missing_years(self, pool):
        pool.conn.on("SELECT id, name FROM orgs", {"id": 7, "name": "Arpan"})
        pool.conn.on("count(*)", {"n": 0, "years": None})
        pool.conn.on("FROM org_financials", {"n": 2, "years": ["FY2023-24", None]})
        out = await catalog_tools.research_goals.ainvoke({"name": "Arpan", "entity_kind": "org",
                                                          "years": "FY2023-24,FY2022-23"})
        assert "In the catalog as [org:7] Arpan." in out and "This is an NGO" in out
        assert "2 row(s) held, years FY2023-24 — still missing FY2022-23" in out
        assert "org_identity -> orgs: 1 row(s) held" in out
        partner = next(s for s, p in pool.conn.sql("FROM funder_activity"))
        assert "partner_org_id = %s" in partner

    async def test_every_year_covered(self, pool):
        pool.conn.on("SELECT id, name FROM orgs", {"id": 7, "name": "Arpan"})
        pool.conn.on("count(*)", {"n": 0, "years": None})
        pool.conn.on("FROM org_financials", {"n": 1, "years": ["FY2023-24"]})
        out = await catalog_tools.research_goals.ainvoke({"name": "Arpan", "entity_kind": "org",
                                                          "years": "FY2023-24"})
        assert "years FY2023-24 — years covered" in out

    async def test_a_failure_is_returned(self, monkeypatch):
        monkeypatch.setattr(catalog_tools, "get_pool", lambda: BrokenPool())
        out = await catalog_tools.research_goals.ainvoke({"name": "Acme", "entity_kind": "funder"})
        assert out == "research_goals failed: RuntimeError: database down"


class TestResearchRows:
    @pytest.fixture(autouse=True)
    def brief(self, monkeypatch):
        async def rows_for(conn, slug):
            return [{"slug": slug, "findings": [{"source_url": STAFF_URL}, {"source_url": VAULT_URL},
                                                {"source_url": PUBLIC}]}]

        async def promotable(row, rows):
            return {**row, "history": rows}
        monkeypatch.setattr(catalog_tools.brief, "rows_for", rows_for)
        monkeypatch.setattr(catalog_tools.brief, "promotable", promotable)

    def row(self):
        return {"slug": "acme", "entity_name": "Acme", "findings": [
            {"source_url": PUBLIC}, {"source_url": STAFF_URL}, {"source_url": VAULT_URL}]}

    async def test_a_member_never_sees_staff_or_vault_findings(self, pool):
        pool.conn.on("FROM entity_research", [self.row()])
        [row] = await catalog_tools._research_rows(pool, "acme", MEMBER)
        assert row["findings"] == [{"source_url": PUBLIC}] and row["private_removed"]
        assert row["history"][0]["findings"] == [{"source_url": PUBLIC}]
        assert pool.conn.calls[0][1] == ("acme",)

    async def test_staff_see_staff_findings_but_not_vault_ones_in_the_shared_row(self, pool):
        pool.conn.on("FROM entity_research", [self.row()])
        [row] = await catalog_tools._research_rows(pool, "", STAFF)
        assert row["findings"] == [{"source_url": PUBLIC}, {"source_url": STAFF_URL}]
        assert pool.conn.calls[0][1] == ()

    async def test_vault_adds_the_readable_orgs_findings(self, pool):
        pool.conn.on("FROM entity_research", [self.row()])
        pool.conn.on("FROM vault_research", [
            {"org_id": 7, "findings": [{"source_url": VAULT_URL}], "documents_read": [12], "titles": {"12": "x"}},
            {"org_id": 9, "findings": [{"source_url": "https://org-vault.sangam.invalid/40"}],
             "documents_read": [40], "titles": None},
        ])
        [row] = await catalog_tools._research_rows(pool, "acme", MEMBER, vault=True)
        assert row["findings"][-1] == {"source_url": VAULT_URL}
        assert row["vault"] == [{"org_id": 7, "documents_read": [12], "titles": {"12": "x"}}]

    async def test_no_readable_vault_leaves_the_row(self, pool):
        row = {"slug": "acme", "entity_name": "Acme", "findings": []}
        assert await catalog_tools._with_vault(pool, row, MEMBER) == row


def rows(monkeypatch, *found):
    async def research_rows(pool, slug, caller=None, *, vault=False):
        return [dict(r) for r in found]
    monkeypatch.setattr(catalog_tools, "_research_rows", research_rows)


def plans(monkeypatch, plan):
    seen = []

    async def promote(conn, row, *, gate):
        seen.append(gate)
        if isinstance(plan, Exception):
            raise plan
        return plan
    monkeypatch.setattr(catalog_tools, "promote", promote)
    return seen


PLAN = {"slug": "acme", "entity": {"kind": "funder", "id": 4, "name": "Acme"}, "held": ["x"], "reasons": [],
        "questions": [{"id": "q1"}],
        "plan": {"same": 3, "items": [{"case": 2, "table": "funder_csr_years"}, {"case": 5, "table": "programs"},
                                      {"case": 5, "table": "programs"}, {"case": 4, "table": "programs"}]}}


class TestCompareAndCoverage:
    async def test_compare_without_research(self, monkeypatch, pool):
        rows(monkeypatch)
        assert (await catalog_tools.compare_with_catalog.ainvoke({"slug": "acme"})).startswith("No saved research")

    async def test_compare_an_ngo_needs_no_questions(self, monkeypatch, pool):
        rows(monkeypatch, {"slug": "arpan", "entity_kind": "org"})
        assert "is an NGO" in await catalog_tools.compare_with_catalog.ainvoke({"slug": "arpan"})

    async def test_compare_groups_the_plan_by_case(self, monkeypatch, pool):
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder"})
        gates = plans(monkeypatch, PLAN)
        out = json.loads(await catalog_tools.compare_with_catalog.ainvoke({"slug": "acme"}))
        assert gates[0].plan
        assert out["same"] == 3 and len(out["new"]) == 2 and len(out["updated"]) == 1
        assert len(out["close_match"]) == 1 and out["older_or_undated"] == [] and out["held"] == ["x"]

    async def test_compare_failure(self, monkeypatch, pool):
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder"})
        plans(monkeypatch, RuntimeError("plan"))
        out = await catalog_tools.compare_with_catalog.ainvoke({"slug": "acme"})
        assert out == "compare_with_catalog failed: RuntimeError: plan"

    @pytest.fixture
    def cover(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(catalog_tools.coverage, "compute", lambda row, report=None: seen.update(
            row=row, report=report) or "cov")
        monkeypatch.setattr(catalog_tools.coverage, "render", lambda cov: f"title\nhead of {cov}\nrest")
        return seen

    async def test_coverage_of_a_funder_reads_its_plan(self, monkeypatch, pool, cover):
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder"})
        plans(monkeypatch, PLAN)
        assert await catalog_tools.coverage_report.ainvoke({"slug": "acme"}) == "title\nhead of cov\nrest"
        assert cover["report"] is PLAN

    async def test_coverage_of_an_ngo_has_no_plan(self, monkeypatch, pool, cover):
        rows(monkeypatch, {"slug": "arpan", "entity_kind": "org"})
        await catalog_tools.coverage_report.ainvoke({"slug": "arpan"})
        assert cover["report"] is None

    async def test_coverage_without_research_and_on_failure(self, monkeypatch, pool):
        rows(monkeypatch)
        assert (await catalog_tools.coverage_report.ainvoke({"slug": "acme"})).startswith("No saved research")
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder"})
        plans(monkeypatch, RuntimeError("x"))
        assert await catalog_tools.coverage_report.ainvoke({"slug": "acme"}) == "coverage_report failed: RuntimeError: x"

    async def test_write_preview(self, monkeypatch, pool, cover):
        rows(monkeypatch)
        assert await catalog_tools.write_preview("acme") == {"questions": [], "planned": [], "coverage": ""}
        rows(monkeypatch, {"slug": "arpan", "entity_kind": "org"})
        org = await catalog_tools.write_preview("arpan")
        assert org["coverage"] == "head of cov" and "An NGO" in org["planned"][0]
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder"})
        plans(monkeypatch, PLAN)
        funder = await catalog_tools.write_preview("acme")
        assert funder["planned"] == ["funder_csr_years: 1 row(s)", "programs: 2 row(s)", "held back: 1"]
        assert funder["questions"] == [{"id": "q1"}]


class TestSavedState:
    async def test_rows_now_needs_an_entity(self, pool):
        assert await catalog_tools._rows_now(pool.conn, "funder", None) is None
        assert await catalog_tools._rows_now(pool.conn, "funder", UNWRITTEN) is None
        assert await catalog_tools._rows_now(pool.conn, "unknown", 4) is None

    async def test_rows_now_counts_each_concept(self, pool):
        pool.conn.on("count(*)", {"n": 3, "years": ["FY2023-24"]})
        counts = await catalog_tools._rows_now(pool.conn, "funder", 4)
        assert counts["identity"] == 1 and counts["csr_year"] == 3

    async def test_record_save_stores_what_was_written(self, monkeypatch, pool):
        monkeypatch.setattr(catalog_tools.coverage, "saved_record", lambda prior, report, after: {"after": after})
        await catalog_tools._record_save(pool.conn, {"id": 31, "saved": None}, {"entity": None})
        [(_sql, params)] = pool.conn.sql("UPDATE entity_research SET saved")
        assert json.loads(params[0]) == {"after": None} and params[1] == 31

    async def test_record_save_keeps_the_stored_record_when_nothing_changed(self, monkeypatch, pool):
        monkeypatch.setattr(catalog_tools.coverage, "saved_record", lambda prior, report, after: None)
        await catalog_tools._record_save(pool.conn, {"id": 31}, {"entity": None})
        assert not pool.conn.calls


class TestCoverageView:
    @pytest.fixture(autouse=True)
    def view(self, monkeypatch):
        monkeypatch.setattr(catalog_tools.coverage, "view", lambda row, **kw: kw)
        monkeypatch.setattr(catalog_tools.coverage, "changes_by_concept",
                            lambda report: {"csr_year": {"added": 2, "updated": 0}})

    async def test_no_research(self, monkeypatch, pool):
        rows(monkeypatch)
        assert await catalog_tools.coverage_view("acme") is None

    async def test_a_saved_row_reads_its_record_without_private_held_lines(self, monkeypatch, pool):
        saved = {"entity": {"id": 4}, "reasons": ["r"], "held": ["Rs 4 lakh from a staff sheet"],
                 "changes": {"a": 1}, "rows_before": {"a": 0}, "rows_after": {"a": 1}, "skipped": {"x": 1}}
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder", "saved": saved, "private_removed": True})
        out = await catalog_tools.coverage_view("acme", MEMBER)
        assert out["stage"] == "saved" and out["held"] == [] and out["after"] == {"a": 1}
        assert out["report"] == {"skipped": {"x": 1}, "held": []}

    async def test_an_unsaved_funder_is_a_dry_run(self, monkeypatch, pool):
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder"})
        plans(monkeypatch, {**PLAN, "entity": {"id": UNWRITTEN, "name": "Acme"}})

        async def rows_now(conn, kind, entity_id):
            return None
        monkeypatch.setattr(catalog_tools, "_rows_now", rows_now)
        out = await catalog_tools.coverage_view("acme", STAFF)
        assert out["stage"] == "planned" and out["entity"] == {"id": None, "name": "Acme"}
        assert out["questions"] == 1 and out["before"]["csr_year"] == 0 and out["after"]["csr_year"] == 2

    async def test_an_unsaved_ngo_has_no_numbers(self, monkeypatch, pool):
        rows(monkeypatch, {"slug": "arpan", "entity_kind": "org"})
        out = await catalog_tools.coverage_view("arpan", STAFF)
        assert out["stage"] == "unsaved" and out["before"] is None


class TestReviewView:
    @pytest.fixture(autouse=True)
    def review(self, monkeypatch):
        r = catalog_tools.review
        monkeypatch.setattr(r, "answers", lambda row: ["answer"])
        monkeypatch.setattr(r, "missing", lambda row: ["missing"])
        monkeypatch.setattr(r, "question", lambda q: {"q": q["id"]})
        monkeypatch.setattr(r, "topic", lambda c: f"topic {c}")
        monkeypatch.setattr(catalog_tools.coverage, "changes_by_concept", lambda report: {
            "csr_year": {"added": 1, "updated": 0}, "program": {"added": 0, "updated": 0}})

    async def test_none_without_research(self, monkeypatch, pool):
        rows(monkeypatch)
        assert await catalog_tools.review_view("acme") is None

    async def test_a_funder(self, monkeypatch, pool):
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder", "canonical_name": "Acme Foundation"})
        plans(monkeypatch, PLAN)
        out = await catalog_tools.review_view("acme", STAFF)
        assert out["name"] == "Acme Foundation" and out["existing"] is True
        assert out["questions"] == [{"q": "q1"}]
        assert out["saves"] == [{"concept": "csr_year", "topic": "topic csr_year", "added": 1, "updated": 0}]

    async def test_an_ngo_asks_only_whether_it_is_the_same(self, monkeypatch, pool):
        rows(monkeypatch, {"slug": "arpan", "entity_kind": "org"})

        async def org_match(conn, row, asking):
            asking.items.append({"outcome": "asked", "id": "same"})
            return Match("close", 7)
        monkeypatch.setattr(catalog_tools, "org_match", org_match)
        out = await catalog_tools.review_view("arpan", STAFF)
        assert out["name"] == "arpan" and out["existing"] is False and out["questions"] == [{"q": "same"}]
        assert out["saves"] == []


NGO = {"slug": "arpan", "entity_kind": "org", "entity_name": "Arpan"}


class TestMaySave:
    async def test_a_funder_needs_a_signed_in_user(self, pool):
        assert await catalog_tools._may_save(pool.conn, MEMBER, {"slug": "acme", "entity_kind": "funder"}) is None
        nobody = CallerScope(None, False)
        assert "signed-in" in await catalog_tools._may_save(pool.conn, nobody, {"slug": "acme"})

    async def test_an_ngo_sangam_does_not_hold(self, monkeypatch, pool):
        async def org_match(conn, row, gate):
            return None
        monkeypatch.setattr(catalog_tools, "org_match", org_match)
        out = await catalog_tools._may_save(pool.conn, ARPAN_STEWARD, NGO)
        assert out == "Arpan is not an NGO Sangam holds yet; the Sangam team adds new NGOs."

    async def test_a_steward_saves_their_own_ngo(self, monkeypatch, pool):
        async def org_match(conn, row, gate):
            return Match("exact", 7)
        monkeypatch.setattr(catalog_tools, "org_match", org_match)
        assert await catalog_tools._may_save(pool.conn, ARPAN_STEWARD, NGO) is None

    async def test_a_member_does_not(self, pool):
        out = await catalog_tools._may_save(pool.conn, MEMBER, {**NGO, "resolved_org_id": 7})
        assert "only its stewards and the Sangam team" in out


class TestSaveToCatalog:
    @pytest.fixture
    def saving(self, monkeypatch, pool):
        state = SimpleNamespace(published=[], finished=True, attempts=0, fail=0)

        async def start(conn, rid, slug, user):
            return 88

        async def finish(conn, pid):
            return state.finished

        async def promote(conn, row, *, gate):
            state.attempts += 1
            if state.attempts <= state.fail:
                raise UniqueViolation("duplicate")
            return {"slug": row["slug"], "facts": {"k": {"state": "written"}}}

        async def record_save(conn, row, report):
            return None

        async def publish_states(p, slug, states):
            state.published.append((slug, states))
        monkeypatch.setattr(catalog_tools.undo, "start", start)
        monkeypatch.setattr(catalog_tools.undo, "finish", finish)
        monkeypatch.setattr(catalog_tools, "promote", promote)
        monkeypatch.setattr(catalog_tools, "_record_save", record_save)
        monkeypatch.setattr(catalog_tools, "_publish_states", publish_states)
        return state

    async def test_only_staff_promote_everything(self, pool):
        with pytest.raises(catalog_tools.SaveRefused, match="one researched organisation at a time"):
            await catalog_tools.save_to_catalog("", MEMBER)

    async def test_no_research_is_a_lookup_error(self, monkeypatch, pool):
        rows(monkeypatch)
        with pytest.raises(LookupError):
            await catalog_tools.save_to_catalog("acme", STAFF)

    async def test_a_refused_caller(self, monkeypatch, pool):
        rows(monkeypatch, {**NGO, "resolved_org_id": 7})
        with pytest.raises(catalog_tools.SaveRefused, match="only its stewards"):
            await catalog_tools.save_to_catalog("arpan", MEMBER)

    async def test_a_save_is_one_undoable_promotion_and_its_states_are_published(self, monkeypatch, pool, saving):
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder", "id": 31})
        [report] = await catalog_tools.save_to_catalog("acme", MEMBER)
        assert report["promotion_id"] == 88
        assert saving.published == [("acme", {"k": {"state": "written"}})]

    async def test_a_race_is_retried_once(self, monkeypatch, pool, saving):
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder"})
        saving.fail, saving.finished = 1, False
        [report] = await catalog_tools.save_to_catalog("acme", STAFF)
        assert saving.attempts == 2 and report["promotion_id"] is None

    async def test_a_second_race_raises(self, monkeypatch, pool, saving):
        rows(monkeypatch, {"slug": "acme", "entity_kind": "funder"})
        saving.fail = 2
        with pytest.raises(UniqueViolation):
            await catalog_tools.save_to_catalog("acme", STAFF)

    async def test_publish_states_writes_back_and_never_raises(self, monkeypatch, pool):
        seen = []

        async def rows_for(conn, slug):
            return [{"slug": slug}]

        async def publish(rws, *, states):
            seen.append((rws, states))
        monkeypatch.setattr(catalog_tools.brief, "rows_for", rows_for)
        monkeypatch.setattr(catalog_tools.brief, "publish", publish)
        await catalog_tools._publish_states(pool, "acme", {"k": 1})
        assert seen == [([{"slug": "acme"}], {"k": 1})]
        await catalog_tools._publish_states(BrokenPool(), "acme", {})


class TestPromoteResearch:
    def saves(self, monkeypatch, result):
        async def save(slug, caller, decisions):
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(catalog_tools, "save_to_catalog", save)

    async def promote(self, args=None):
        with running_as(STAFF):
            return await catalog_tools.promote_research.ainvoke({"slug": "acme"} if args is None else args)

    async def test_refused_and_missing(self, monkeypatch):
        self.saves(monkeypatch, catalog_tools.SaveRefused("not yours"))
        assert await self.promote() == "REFUSED: not yours"
        self.saves(monkeypatch, LookupError("acme"))
        assert await self.promote() == "No saved research for 'acme'. Research first."
        assert await self.promote({}) == "No saved research. Research first."

    async def test_a_failure_is_returned(self, monkeypatch):
        self.saves(monkeypatch, RuntimeError("boom"))
        assert await self.promote() == "promote_research failed: RuntimeError: boom"

    async def test_the_report_names_everything(self, monkeypatch):
        self.saves(monkeypatch, [{
            "slug": "acme", "entity": {"name": "Acme", "kind": "funder", "status": "added", "id": 4},
            "csr_years": [{"fiscal_year": "FY2023-24", "status": "added"}],
            "written": {"programs": {"added": 2, "matched": 1}},
            "changes": [{"table": "funders", "label": "Acme", "row": 4, "changes": {"website": {"old": None,
                                                                                                "new": "x"}}},
                        {"table": "programs", "label": "Water", "stored_name": "Water", "new_name": "Water+"}],
            "reasons": ["no writer for rfp"], "held": ["a close name"], "conflicts": ["website differs"],
            "skipped": {"rfp": 2},
        }, {"slug": "zed", "entity": None, "csr_years": [], "reasons": [], "skipped": {}}])
        out = await self.promote()
        assert out.startswith("Promoted 2 researched organisation(s) into the catalog.")
        assert "  Acme: funder added [funder:4] · CSR years FY2023-24 added" in out
        assert "    programs: 2 added, 1 matched" in out
        assert "    changed funders Acme 4: website None → 'x'" in out
        assert "    changed programs Water : 'Water' → 'Water+'" in out
        assert "  acme: not promoted — no writer for rfp" in out and "    held back: a close name" in out
        assert "    conflict: website differs" in out and "still research only (no writer): 2 rfp" in out


class TestRecordRegistryCheck:
    ARGS = {"org": "arpan", "id_type": "pan", "status": "registered", "source_url": PUBLIC}

    async def test_the_checker_is_the_signed_in_user(self, monkeypatch, pool):
        seen = {}

        async def record(p, **kw):
            seen.update(kw)
            return "Recorded"
        monkeypatch.setattr(catalog_tools.manual_checks, "record", record)
        token = chat_user_id.set(STAFF.user_id)
        try:
            with running_as(STAFF):
                out = await catalog_tools.record_registry_check.ainvoke({**self.ARGS, "evidence_document_id": 3})
        finally:
            chat_user_id.reset(token)
        assert out == "Recorded" and seen["user_id"] == STAFF.user_id and seen["document_id"] == 3

    async def test_a_failure_is_returned(self, monkeypatch, pool):
        async def record(p, **kw):
            raise RuntimeError("tx")
        monkeypatch.setattr(catalog_tools.manual_checks, "record", record)
        with running_as(STAFF):
            out = await catalog_tools.record_registry_check.ainvoke(self.ARGS)
        assert out == "record_registry_check failed: RuntimeError: tx"

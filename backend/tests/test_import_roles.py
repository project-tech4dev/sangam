"""Import by role: what members, stewards and staff may run, save and see."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from langchain_core.messages import SystemMessage

from app.core import security
from app.core.security import CallerScope, chat_scope
from app.ingest import caller, promote
from app.ingest.tools import catalog_tools, pipeline_tools, research_tools
from app.ingest.writer import Gate

ME = UUID(int=2)
MEMBER = CallerScope(ME, False, {7: "member"}, {7: "Arpan"})
STEWARD = CallerScope(UUID(int=3), False, {7: "steward", 8: "steward"}, {7: "Arpan", 8: "Kabil"})
STAFF = CallerScope(UUID(int=1), True)

STAFF_URL = "https://staff-sources.sangam.invalid/12"
PUBLIC_URL = "https://example.org/csr"


@contextmanager
def running_as(scope: CallerScope | None):
    token = chat_scope.set(scope)
    try:
        yield
    finally:
        chat_scope.reset(token)


class _Conn:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    async def execute(self, sql, params=()):
        self.sql.append(sql)
        return SimpleNamespace(fetchone=self._one, fetchall=self._all)

    async def _one(self):
        return self.rows[0] if self.rows else None

    async def _all(self):
        return self.rows

    @asynccontextmanager
    async def transaction(self):
        yield


class _Pool:
    def __init__(self, rows=()):
        self.conn = _Conn(list(rows))

    @asynccontextmanager
    async def connection(self):
        yield self.conn


STAFF_TOOLS = [
    (pipeline_tools.plan_import, {}),
    (pipeline_tools.run_import_now, {"goal": "x"}),
    (pipeline_tools.import_run_summary, {}),
    (pipeline_tools.pending_resolutions, {}),
    (pipeline_tools.list_storage_buckets, {}),
    (pipeline_tools.list_bucket_files, {"bucket": "staff-sources"}),
    (pipeline_tools.select_source_files, {"paths": ["staff-sources/a.xlsx"]}),
    (pipeline_tools.read_source_rows, {"name": "Arpan"}),
    (pipeline_tools.read_workbook, {"documents": [1]}),
    (catalog_tools.record_registry_check, {"org": "arpan", "id_type": "pan", "status": "registered",
                                           "source_url": PUBLIC_URL}),
    (research_tools.publish_brief, {}),
]


class TestStaffToolsRefuseEveryoneElse:
    @pytest.mark.parametrize("scope", [MEMBER, STEWARD, None], ids=["member", "steward", "no caller"])
    @pytest.mark.parametrize(("tool", "args"), STAFF_TOOLS, ids=[t.name for t, _ in STAFF_TOOLS])
    async def test_refused_as_a_string(self, tool, args, scope, monkeypatch):
        monkeypatch.setattr(pipeline_tools, "get_pool", lambda: pytest.fail("reached the database"))
        with running_as(scope):
            out = await tool.ainvoke(args)
        assert out.startswith("REFUSED") and tool.name in out

    def test_staff_pass(self):
        with running_as(STAFF):
            assert caller.staff_only("plan_import") is None


class TestSavingResearch:
    from app.ingest.research_records import EntityResearch

    FUNDER = EntityResearch(entity_name="Acme Foundation", entity_kind="funder", status="not_found",
                            summary="Nothing public about this one, in any source read.")
    NGO = EntityResearch(entity_name="Arpan", entity_kind="org", status="not_found",
                         summary="Nothing public about this one, in any source read.")

    async def test_a_member_does_not_research_an_ngo(self, monkeypatch):
        monkeypatch.setattr(research_tools, "get_pool", lambda: pytest.fail("reached the database"))
        with running_as(MEMBER):
            out = await research_tools.save_research.ainvoke({"findings": self.NGO})
        assert out.startswith("REFUSED")

    async def test_a_member_does_not_overwrite_someone_elses_research_today(self, monkeypatch):
        pool = _Pool([{"fact_count": 0, "researched_by": UUID(int=9)}])
        monkeypatch.setattr(research_tools, "get_pool", lambda: pool)
        with running_as(MEMBER):
            out = await research_tools.save_research.ainvoke({"findings": self.FUNDER, "replace": True})
        assert out.startswith("REFUSED") and "already researched" in out
        assert not any("INSERT" in sql for sql in pool.conn.sql)

    async def test_the_save_records_who_made_it(self, monkeypatch):
        pool = _Pool([])
        monkeypatch.setattr(research_tools, "get_pool", lambda: pool)
        seen = {}

        async def execute(sql, params=()):
            if "INSERT" in sql:
                seen.update(sql=sql, params=params)
            return SimpleNamespace(fetchone=_none)

        async def _none():
            return None

        pool.conn.execute = execute
        with running_as(MEMBER):
            await research_tools.save_research.ainvoke({"findings": self.FUNDER})
        assert "researched_by" in seen["sql"] and seen["params"][-1] == ME


class TestPromotingResearch:
    async def test_a_member_promotes_one_slug_at_a_time(self, monkeypatch):
        monkeypatch.setattr(catalog_tools, "get_pool", lambda: pytest.fail("reached the database"))
        with running_as(MEMBER):
            out = await catalog_tools.promote_research.ainvoke({})
        assert out.startswith("REFUSED")

    async def test_anyone_signed_in_may_save_a_funder(self):
        assert await catalog_tools._may_save(_Conn([]), MEMBER, {"slug": "acme", "entity_kind": "funder"}) is None
        nobody = CallerScope(None, False)
        assert await catalog_tools._may_save(_Conn([]), nobody, {"slug": "acme", "entity_kind": "funder"})

    @pytest.mark.parametrize(("scope", "org", "allowed"), [
        (STEWARD, 8, True), (STEWARD, 9, False), (MEMBER, 7, False),
    ])
    async def test_an_ngo_needs_its_steward(self, scope, org, allowed):
        row = {"slug": "kabil", "entity_kind": "org", "resolved_org_id": org}
        assert (await catalog_tools._may_save(_Conn([]), scope, row) is None) is allowed

    async def test_a_new_ngo_is_the_teams_to_add(self, monkeypatch):
        from app.ingest.matcher import Match

        async def no_match(conn, name, identifiers=None):
            return Match(method="none")

        monkeypatch.setattr(promote, "resolve_org", no_match)
        why = await catalog_tools._may_save(_Conn([]), STEWARD, {"slug": "new-ngo", "entity_kind": "org"})
        assert "Sangam team adds new NGOs" in why

    @pytest.mark.parametrize(("choice", "allowed"), [("update", True), ("new", False), (None, False)])
    async def test_a_steward_who_says_a_close_name_is_theirs_may_save(self, monkeypatch, choice, allowed):
        from app.ingest.matcher import Match

        kabil = {"id": 8, "name": "Kabil Trust", "score": 0.7}

        async def close(conn, name, identifiers=None):
            return Match("trigram", None, 0.7, [kabil])

        monkeypatch.setattr(promote, "resolve_org", close)
        asked = Gate(plan=True)
        asked.on_entity("orgs", "Kabil", kabil)
        decisions = {asked.items[0]["id"]: choice} if choice else {}
        row = {"slug": "kabil", "entity_name": "Kabil", "entity_kind": "org"}
        assert (await catalog_tools._may_save(_Conn([]), STEWARD, row, decisions) is None) is allowed


ROW = {"slug": "acme", "entity_kind": "funder", "summary": "From the sheet", "fact_count": 2,
       "sources_read": [STAFF_URL, PUBLIC_URL],
       "findings": [{"concept": "csr_year", "source_url": STAFF_URL, "evidence": "cell B12 says 4 crore"},
                    {"concept": "rfp", "source_url": PUBLIC_URL, "evidence": "Applications open in May"}]}


class TestOnlyStaffSeePrivateFindings:
    def test_private_findings_and_sources_are_removed(self):
        out = caller.without_private(ROW)
        assert [f["source_url"] for f in out["findings"]] == [PUBLIC_URL]
        assert out["sources_read"] == [PUBLIC_URL] and out["fact_count"] == 1 and out["private_removed"]

    async def test_research_rows_are_filtered_for_non_staff(self):
        for scope, n in [(MEMBER, 1), (STAFF, 2)]:
            rows = await catalog_tools._research_rows(_Pool([dict(ROW)]), "acme", scope)
            assert len(rows[0]["findings"]) == n

    async def test_a_tool_without_a_caller_sees_public_findings_only(self):
        with running_as(None):
            rows = await catalog_tools._research_rows(_Pool([dict(ROW)]), "acme")
        assert len(rows[0]["findings"]) == 1


class TestTheSupervisorKnowsWhoItWorksFor:
    def test_a_member_is_offered_funders_only(self):
        note = caller.caller_note(MEMBER)
        assert "member of Arpan" in note and "funders only" in note

    def test_a_steward_hears_its_ngos(self):
        assert "Arpan, Kabil" in caller.caller_note(STEWARD)

    def test_staff_get_everything(self):
        assert "Sangam team" in caller.caller_note(STAFF)

    def test_anyone_else_skips_the_staff_workbook_pause(self):
        for scope in (MEMBER, STEWARD):
            assert "do not call list_storage_buckets, list_bucket_files" in caller.caller_note(scope)

    def test_the_note_is_appended_to_the_system_message(self):
        from app.ingest.middleware import CallerNote

        request = SimpleNamespace(system_message=SystemMessage("Base prompt"),
                                  override=lambda **kw: kw["system_message"])
        with running_as(MEMBER):
            message = CallerNote().wrap_model_call(request, lambda r: r)
        assert message.text.startswith("Base prompt") and "funders only" in message.text


class TestTheResearchListIsTheCallers:
    @pytest.fixture
    def listed(self, monkeypatch):
        from app.api.routes import ingest as ingest_api

        seen = {}

        async def fake(pool, *, limit, mine):
            seen["mine"] = mine
            return [{"id": 1, "entity_name": "Acme", "canonical_name": None, "entity_kind": "funder",
                     "slug": "acme", "status": "complete", "stopped_reason": None, "summary": "From the sheet",
                     "fact_count": 2, "sources_read": [STAFF_URL, PUBLIC_URL], "not_found": [],
                     "researched_at": "2026-10-09T10:00:00Z", "saved_at": None, "resolved_org_id": None,
                     "resolved_funder_id": None, "has_private": True,
                     "promotion_id": 5, "saved_by": "Asha"}]

        monkeypatch.setattr(ingest_api.repo, "list_research", fake)
        return seen

    async def _get(self, client_for, scope):
        from app.api.routes import ingest as ingest_api
        from tests.conftest import make_app
        from tests.test_access import client

        app = make_app(ingest_api.router)
        app.dependency_overrides[security.request_scope] = lambda: scope
        async with client(app) as c:
            return (await c.get("/api/ingest/research")).json()

    async def test_a_steward_sees_its_own_and_its_ngos(self, listed, client_for):
        body = await self._get(client_for, STEWARD)
        assert listed["mine"] == (STEWARD.user_id, [7, 8])
        assert body[0]["sources_read"] == [PUBLIC_URL]
        assert body[0]["summary"].startswith("This research also read private sources")
        assert body[0]["promotion_id"] is None and body[0]["saved_by"] is None  # undo is staff's

    async def test_staff_see_everything_as_saved(self, listed, client_for):
        body = await self._get(client_for, STAFF)
        assert listed["mine"] is None and body[0]["summary"] == "From the sheet"
        assert body[0]["promotion_id"] == 5 and body[0]["saved_by"] == "Asha"


@pytest.mark.integration
class TestTheResearchListQuery:
    """Against Postgres: a member with no stewarded orgs sends an empty array."""

    @pytest.mark.parametrize("mine", [None, (ME, []), (ME, [7, 8])])
    async def test_runs_for_every_caller(self, db, mine):
        from app.repositories import ingest as repo
        from tests.test_storage import _PoolOf

        rows = await repo.list_research(_PoolOf(db), limit=5, mine=mine)
        assert all("has_private" in r for r in rows)


class _TxPool:
    """A pool whose connection and transaction do nothing; the undo module is faked."""

    @asynccontextmanager
    async def connection(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        yield


class TestStaffUndoAndDelete:
    @pytest.fixture
    def app_as(self, monkeypatch):
        from app.api.routes import ingest as ingest_api
        from app.db.pool import get_pool
        from app.ingest import undo
        from tests.conftest import make_app
        from tests.test_access import as_caller

        async def fake_undo(conn, promotion_id, user_id):
            if promotion_id == 404:
                raise LookupError(promotion_id)
            if promotion_id == 409:
                raise undo.UndoRefused("a funders row has changed since this save")
            return {"promotion_id": promotion_id, "slug": "acme", "removed": 3, "restored": 1}

        async def fake_delete(conn, slug):
            return {"saved": None, "gone": 0}.get(slug, 2)

        monkeypatch.setattr(undo, "undo", fake_undo)
        monkeypatch.setattr(undo, "delete_research", fake_delete)

        def _make(principal):
            app = as_caller(make_app(ingest_api.router), principal)
            app.dependency_overrides[get_pool] = _TxPool
            return app

        return _make

    async def test_members_cannot_undo_or_delete(self, app_as):
        from tests.test_access import MEMBER, client

        async with client(app_as(MEMBER)) as c:
            assert (await c.post("/api/ingest/promotions/5/undo")).status_code == 403
            assert (await c.delete("/api/ingest/research/acme")).status_code == 403

    async def test_staff_undo(self, app_as):
        from tests.test_access import client

        async with client(app_as(security.DEV_USER)) as c:
            done = await c.post("/api/ingest/promotions/5/undo")
            missing = await c.post("/api/ingest/promotions/404/undo")
            refused = await c.post("/api/ingest/promotions/409/undo")
        assert done.json() == {"promotion_id": 5, "slug": "acme", "removed": 3, "restored": 1}
        assert missing.status_code == 404
        assert refused.status_code == 409 and refused.json()["detail"].startswith("Nothing was undone: a funders row")

    async def test_staff_delete(self, app_as):
        from tests.test_access import client

        async with client(app_as(security.DEV_USER)) as c:
            assert (await c.delete("/api/ingest/research/acme")).status_code == 204
            assert (await c.delete("/api/ingest/research/gone")).status_code == 404
            saved = await c.delete("/api/ingest/research/saved")
        assert saved.status_code == 409 and "Undo the save first" in saved.json()["detail"]


class TestSaveFromTheScreen:
    @pytest.fixture
    def post(self, monkeypatch):
        from app.api.routes import ingest as ingest_api
        from tests.conftest import make_app
        from tests.test_access import client

        seen = {}

        async def fake_save(slug, caller, decisions):
            seen.update(slug=slug, caller=caller, decisions=decisions)
            if slug == "missing":
                raise LookupError(slug)
            if slug == "kabil" and not caller.is_staff:
                raise catalog_tools.SaveRefused("Kabil is an NGO; only its stewards and the Sangam team save research about it.")
            return [{"slug": slug, "entity": {"kind": "funder", "id": 9, "name": "Acme", "status": "created"},
                     "promotion_id": 4, "written": {"funders": {"added": 1}, "contacts": {"same": 2, "updated": 1}},
                     "held": ["contact: no source"], "reasons": []}]

        monkeypatch.setattr(catalog_tools, "save_to_catalog", fake_save)

        async def _post(scope, slug, body):
            app = make_app(ingest_api.router)
            app.dependency_overrides[security.request_scope] = lambda: scope
            async with client(app) as c:
                return await c.post(f"/api/ingest/research/{slug}/save", json=body)

        return _post, seen

    async def test_a_member_saves_a_funder_with_their_answers(self, post):
        _post, seen = post
        res = await _post(MEMBER, "acme", {"decisions": {"q1": "update"}})
        assert res.status_code == 200 and seen["decisions"] == {"q1": "update"} and seen["caller"] is MEMBER
        body = res.json()
        assert body["entity"]["id"] == 9 and body["written"] == 2 and body["held"] == 1
        assert body["promotion_id"] is None  # undo is staff's

    async def test_staff_get_the_promotion(self, post):
        _post, _ = post
        assert (await _post(STAFF, "acme", {})).json()["promotion_id"] == 4

    async def test_refusals_and_missing_research(self, post):
        _post, _ = post
        refused = await _post(MEMBER, "kabil", {})
        assert refused.status_code == 403 and refused.json()["detail"].startswith("Kabil is an NGO")
        assert (await _post(MEMBER, "missing", {})).status_code == 404


class TestACloseNameIsAsked:
    """Research whose name only resembles a stored NGO's waits for "the same organisation?"."""

    CLOSE = {"id": 12, "name": "Peoples Resource Development Association", "score": 0.6}

    def _answer(self, choice):
        from app.ingest.matcher import Match

        asked = Gate(plan=True)
        asked.on_entity("orgs", "PRDA", self.CLOSE)
        gate = Gate({asked.items[0]["id"]: choice} if choice else {})
        report = {"reasons": []}
        return promote._answered(gate, "orgs", "PRDA", Match("trigram", None, 0.6, [self.CLOSE]), report), gate, report

    def test_the_same_saves_to_the_stored_ngo_by_alias(self):
        match, _, _ = self._answer("update")
        assert (match.method, match.entity_id) == ("alias", 12)

    def test_different_makes_a_new_one(self):
        match, _, _ = self._answer("new")
        assert match.method == "none" and not match.resolved

    @pytest.mark.parametrize("choice", [None, "skip"])
    def test_unanswered_or_unsure_holds_it(self, choice):
        match, gate, report = self._answer(choice)
        assert match is None and "Not merged" in report["reasons"][0]
        assert [q["stored_name"] for q in gate.asked()] == ([self.CLOSE["name"]] if choice is None else [])

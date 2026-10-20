"""The adapter path's tools: the registry summary, a plan, a run, its summary and the review queue."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ingest.calls import pull
from app.ingest.news import pipeline
from app.ingest.news.pipeline import Selection
from app.ingest.sources import SOURCES
from app.ingest.tools import pipeline_tools
from tests.cov_ingest_fakes import BrokenPool, ScriptPool, running_as
from tests.test_import_roles import MEMBER, STAFF


@pytest.fixture
def pool(monkeypatch):
    p = ScriptPool()
    monkeypatch.setattr(pipeline_tools, "get_pool", lambda: p)
    monkeypatch.setattr(pipeline_tools, "get_settings", lambda: SimpleNamespace(utility_model="haiku"))
    return p


async def as_staff(tool, args):
    with running_as(STAFF):
        return await tool.ainvoke(args)


class TestListImportSources:
    async def test_counts_by_default(self):
        out = await pipeline_tools.list_import_sources.ainvoke({})
        assert out.startswith(f"{len(SOURCES)} sources registered.")
        assert "Can be read AND have an adapter" in out and "By category:" in out
        assert "Held, by rule:" in out

    async def test_a_category_narrows_it(self):
        out = await pipeline_tools.list_import_sources.ainvoke({"category": "Media"})
        assert "sources registered in Media." in out and "By category:" not in out

    async def test_an_unknown_category(self):
        out = await pipeline_tools.list_import_sources.ainvoke({"category": "banks"})
        assert out.startswith("Unknown category 'banks'. Use one of: funder")

    async def test_detail_by_key_quotes_the_basis(self):
        key, s = next(iter(SOURCES.items()))
        out = await pipeline_tools.list_import_sources.ainvoke({"detail": key})
        assert f"{key} — {s.name}" in out and "basis:" in out and "rule:" in out

    async def test_detail_by_rule(self):
        out = await pipeline_tools.list_import_sources.ainvoke({"detail": "no_scraping_manual_entry_allowed"})
        assert out.count("[HELD]") >= 1 and "[RUNS]" not in out

    async def test_detail_that_matches_nothing(self):
        out = await pipeline_tools.list_import_sources.ainvoke({"detail": "nothing-like-this"})
        assert out == "Nothing registered matches 'nothing-like-this'."

    async def test_a_failure_is_returned(self, monkeypatch):
        monkeypatch.setattr(pipeline_tools, "runnable_for", lambda keys: 1 / 0)
        out = await pipeline_tools.list_import_sources.ainvoke({})
        assert out.startswith("list_import_sources failed: division by zero")


class TestPlanImport:
    @pytest.fixture(autouse=True)
    def baseline(self, monkeypatch, pool):
        async def baseline():
            return {"funders": 40, "funder_csr_years": 120}
        monkeypatch.setattr(pipeline_tools, "catalog_baseline", baseline)

    async def test_a_plan_over_everything(self, monkeypatch):
        async def news(names, feeds=""):
            return "tavily_news: 3 subjects"
        monkeypatch.setattr(pipeline_tools, "_news_plan_line", news)
        out = await as_staff(pipeline_tools.plan_import, {"sources": "tavily_news, nope"})
        assert out.startswith("PLAN — nothing is written by this step.")
        assert "No name given" in out and "tavily_news: 3 subjects" in out
        assert "Unknown source names, ignored: nope" in out
        assert "funders 40, funder csr years 120" in out

    async def test_a_held_source_is_counted_by_rule(self):
        held = next(k for k, s in SOURCES.items() if not s.dispatchable)
        out = await as_staff(pipeline_tools.plan_import, {"sources": held, "funders": "Acme"})
        assert "nothing: no requested source both may be read" in out
        assert "Will NOT pull (1 held by their access rule)" in out and "No name given" not in out

    async def test_an_adapter_source_names_its_basis(self, monkeypatch):
        s = next(s for s in SOURCES.values() if s.dispatchable)
        monkeypatch.setattr(pipeline_tools, "runnable_for", lambda keys: frozenset({s.key}))
        out = await as_staff(pipeline_tools.plan_import, {"sources": s.key, "limit": 4})
        assert f"{s.key} ({s.host}) — up to 4 items" in out and "permitted because:" in out

    async def test_a_permitted_source_without_an_adapter(self, monkeypatch):
        s = next(s for s in SOURCES.values() if s.dispatchable)
        monkeypatch.setattr(pipeline_tools, "runnable_for", lambda keys: frozenset())
        out = await as_staff(pipeline_tools.plan_import, {"sources": s.key})
        assert f"Permitted, but nothing reads them yet (1): {s.key}" in out

    async def test_a_failure_is_returned(self, monkeypatch):
        async def broken():
            raise RuntimeError("no catalog")
        monkeypatch.setattr(pipeline_tools, "catalog_baseline", broken)
        assert await as_staff(pipeline_tools.plan_import, {}) == "plan_import failed: no catalog"


class TestNewsPlanLine:
    async def test_names_the_registry_does_not_hold(self, monkeypatch, pool):
        async def select(p, names, feeds):
            return Selection([], [], [], [], names)
        monkeypatch.setattr(pipeline, "select", select)
        out = await pipeline_tools._news_plan_line(["Nobody"])
        assert "none of those names is in the Registry" in out

    async def test_a_plan_line(self, monkeypatch, pool):
        async def select(p, names, feeds):
            assert feeds == ["fcra"]
            return Selection([1], [2], feeds, ["Arpan"], [])

        async def plan_for(p, *, org_ids, funder_ids, feeds):
            assert (org_ids, funder_ids) == ([1], [2])
            return SimpleNamespace(line="2 subjects, about $0.10")
        monkeypatch.setattr(pipeline, "select", select)
        monkeypatch.setattr(pipeline, "plan_for", plan_for)
        out = await pipeline_tools._news_plan_line(["Arpan"], "fcra")
        assert out == "tavily_news: 2 subjects, about $0.10. Never creates a funder or an organisation."


class TestRunImportNow:
    async def test_needs_a_goal(self, pool):
        assert "needs a goal" in await as_staff(pipeline_tools.run_import_now, {"goal": "  "})

    async def test_an_adapter_run_returns_its_summary(self, monkeypatch, pool):
        seen = {}

        async def run_import(keys, **kw):
            seen.update(keys=keys, **kw)
            return {"error": "No source could run."}
        monkeypatch.setattr(pipeline_tools, "run_import", run_import)
        monkeypatch.setattr(pipeline_tools, "resolve_model", lambda name: f"model:{name}")
        out = await as_staff(pipeline_tools.run_import_now,
                             {"goal": " FY figures ", "funders": "Acme, ", "years": "FY2024-25", "limit": 3})
        assert out == "No source could run."
        assert seen == {"keys": None, "goal": "FY figures", "funders": ["Acme"], "years": ["FY2024-25"],
                        "model": "model:haiku", "limit": 3}

    async def test_a_news_pull_refuses_other_sources_out_loud(self, monkeypatch, pool):
        items = []

        async def select(p, names, feeds):
            return Selection([1], [], feeds, ["Arpan"], [])

        async def create_run(p, **kw):
            assert kw["goal"] == "news" and kw["started_by"] == STAFF.user_id
            return 77

        async def record(conn, run_id, key, kind, status, *, reason):
            items.append((run_id, key, status))

        async def execute_run(p, run_id, deps):
            return {"run": run_id, "stories": 4}
        monkeypatch.setattr(pipeline, "select", select)
        monkeypatch.setattr(pipeline, "create_run", create_run)
        monkeypatch.setattr(pipeline, "execute_run", execute_run)
        monkeypatch.setattr(pipeline.Deps, "from_settings", classmethod(lambda cls, s: "deps"))
        monkeypatch.setattr(pipeline_tools, "record_item", record)
        out = await as_staff(pipeline_tools.run_import_now,
                             {"goal": "news", "funders": "Arpan", "sources": "tavily_news,gdelt", "feeds": "fcra"})
        assert out == "run: 77\nstories: 4"
        assert items == [(77, "gdelt", "refused")]

    async def test_a_news_pull_for_unknown_names_runs_nothing(self, monkeypatch, pool):
        async def select(p, names, feeds):
            return Selection([], [], [], [], names)
        monkeypatch.setattr(pipeline, "select", select)
        monkeypatch.setattr(pipeline, "create_run", lambda *a, **k: pytest.fail("created a run"))
        out = await as_staff(pipeline_tools.run_import_now,
                             {"goal": "news", "funders": "Nobody", "sources": "tavily_news"})
        assert "none of those names is in the Registry" in out

    async def test_an_unknown_feed_is_a_returned_failure(self, pool):
        out = await as_staff(pipeline_tools.run_import_now, {"goal": "g", "sources": "tavily_news", "feeds": "x"})
        assert out.startswith("run_import_now failed: ValueError: unknown feed x")

    async def test_a_calls_pull_for_named_funders(self, monkeypatch, pool):
        pool.conn.on("FROM funders", [{"slug": "acme", "name": "acme foundation"}])
        seen = {}

        async def run(p, deps, slugs):
            seen["slugs"] = slugs
            return ["acme: 2 open calls"]
        monkeypatch.setattr(pull, "run", run)
        monkeypatch.setattr(pull.Deps, "from_settings", classmethod(lambda cls, s: "deps"))
        out = await as_staff(pipeline_tools.run_import_now, {
            "goal": "calls", "funders": "Acme Foundation, Ghost", "sources": "funder_calls,tavily_x"})
        assert seen["slugs"] == ["acme"]
        assert out.splitlines() == ["Ghost: no funder in Sangam by this name; nothing read.",
                                    "tavily_x: not run, a calls pull runs alone; ask for it separately.",
                                    "acme: 2 open calls"]

    async def test_a_calls_pull_with_no_known_funder_reads_nothing(self, monkeypatch, pool):
        monkeypatch.setattr(pull, "run", lambda *a: pytest.fail("pulled"))
        out = await as_staff(pipeline_tools.run_import_now,
                             {"goal": "calls", "funders": "Ghost", "sources": "funder_calls"})
        assert out.endswith("none of those names is a funder in Sangam; nothing was read.")

    async def test_a_calls_pull_for_everyone(self, monkeypatch, pool):
        async def run(p, deps, slugs):
            return [f"slugs={slugs}"]
        monkeypatch.setattr(pull, "run", run)
        monkeypatch.setattr(pull.Deps, "from_settings", classmethod(lambda cls, s: "deps"))
        out = await as_staff(pipeline_tools.run_import_now, {"goal": "calls", "sources": "funder_calls"})
        assert out == "slugs=None"


class TestRunSummary:
    async def test_no_run_yet(self, pool):
        assert await as_staff(pipeline_tools.import_run_summary, {}) == "No import has been run yet."

    async def test_the_latest_run(self, monkeypatch, pool):
        pool.conn.on("FROM ingest_runs", {"id": 9})

        async def summarise(run_id):
            return {"error": f"run {run_id}"}
        monkeypatch.setattr(pipeline_tools, "summarise", summarise)
        assert await as_staff(pipeline_tools.import_run_summary, {}) == "run 9"

    async def test_a_failure_is_returned(self, monkeypatch):
        monkeypatch.setattr(pipeline_tools, "get_pool", lambda: BrokenPool())
        assert await as_staff(pipeline_tools.import_run_summary, {}) == "import_run_summary failed: database down"


class TestPendingResolutions:
    async def test_nothing_waiting(self, pool):
        assert await as_staff(pipeline_tools.pending_resolutions, {}) == "Nothing is waiting for review."

    async def test_rows_name_their_candidates_and_the_limit_is_capped(self, pool):
        pool.conn.on("FROM resolution_queue", [
            {"id": 1, "raw_name": "Acme Fdn", "entity_kind": "funder", "source": "csr", "source_url": "https://a",
             "candidates": [{"name": "Acme Foundation", "id": 4, "score": 0.81}]},
            {"id": 2, "raw_name": "Zed", "entity_kind": "funder", "source": "csr", "source_url": "https://z",
             "candidates": None},
        ])
        out = await as_staff(pipeline_tools.pending_resolutions, {"limit": 500})
        assert "#1 'Acme Fdn' from csr → Acme Foundation [funder:4] (0.81)" in out
        assert "#2 'Zed' from csr → no candidate above the threshold" in out
        assert pool.conn.calls[0][1] == (100,)

    async def test_a_failure_is_returned(self, monkeypatch):
        monkeypatch.setattr(pipeline_tools, "get_pool", lambda: BrokenPool())
        assert await as_staff(pipeline_tools.pending_resolutions, {}) == "pending_resolutions failed: database down"


class TestFormatSummary:
    def summary(self, **over):
        return {"run_id": 3, "status": "succeeded", "duration_seconds": 12, "goal": None, "subjects": [],
                "fiscal_years": None, "sources_processed": ["mca", "bse"], "sources_refused": ["x", "y"],
                "sources_failed": [], "totals": {"added": 2}, "by_source": {"mca": 2},
                "written": [{"status": "added", "subject": "Acme", "target_table": "funders", "changes": ["name"]},
                            {"status": "matched", "subject": "Zed", "target_table": "funders", "changes": []}],
                "sources_without_adapter": ["ngo_darpan"],
                "needs_attention": [{"status": "refused", "subject": None, "source": f"s{i}", "reason": "held"}
                                    for i in range(17)], **over}

    def test_every_part(self):
        out = pipeline_tools.format_summary(self.summary())
        assert out.startswith("Import run #3 — succeeded in 12s")
        assert "goal:      not recorded" in out and "refused:   2 held" in out
        assert "records:   2 added, 0 updated, 0 already current, 0 queued" in out
        assert "bse ran and found nothing new" in out
        assert "  added: Acme → funders name" in out and "  matched: Zed → funders\n" in out
        assert "Permitted but not built yet (1): ngo_darpan" in out
        assert "refused: s0 — held" in out and "… and 2 more" in out

    def test_an_error_is_the_whole_report(self):
        assert pipeline_tools.format_summary({"error": "boom"}) == "boom"


class TestChooseSources:
    async def test_a_vault_pick_is_checked_and_named(self, monkeypatch, pool):
        async def in_vault(p, org, ids):
            return ids
        monkeypatch.setattr(pipeline_tools.vault, "in_vault", in_vault)
        with running_as(MEMBER):
            msg = await pipeline_tools.choose_sources.ainvoke(
                {"name": "choose_sources", "id": "c", "type": "tool_call",
                 "args": {"web": False, "library": False, "vault_org": 7, "vault_docs": [12, 12, 3]}})
        assert msg.artifact["vault_docs"] == [3, 12] and msg.artifact["vault_org"] == 7
        assert "Doc Vault of org 7: documents 3, 12" in msg.content

    async def test_a_file_outside_the_vault_is_refused(self, monkeypatch, pool):
        async def in_vault(p, org, ids):
            return set()
        monkeypatch.setattr(pipeline_tools.vault, "in_vault", in_vault)
        with running_as(MEMBER):
            msg = await pipeline_tools.choose_sources.ainvoke(
                {"name": "choose_sources", "id": "c", "type": "tool_call",
                 "args": {"vault_org": 7, "vault_docs": [12]}})
        assert msg.content.startswith("REFUSED: some of those files") and msg.artifact is None

    async def test_a_bad_staff_path_is_listed_as_refused(self, monkeypatch, pool):
        monkeypatch.setattr(pipeline_tools.staff_sources, "check_pick", lambda p: "not a staff workbook")
        msg = await as_staff(pipeline_tools.choose_sources, {"name": "choose_sources", "id": "c",
                                                              "type": "tool_call",
                                                              "args": {"staff_paths": ["x/y.csv"]}})
        assert "- refused: not a staff workbook" in msg.content and msg.artifact["staff_docs"] == []

    async def test_a_failure_returns_no_artifact(self, monkeypatch):
        monkeypatch.setattr(pipeline_tools, "get_pool", lambda: 1 / 0)
        msg = await as_staff(pipeline_tools.choose_sources, {"name": "choose_sources", "id": "c",
                                                              "type": "tool_call", "args": {}})
        assert msg.content == "choose_sources failed: ZeroDivisionError" and msg.artifact is None


class TestStaffWorkbooks:
    async def test_no_documents_reads_nothing(self, pool):
        out = await as_staff(pipeline_tools.read_source_rows, {"name": "Acme"})
        assert out.startswith("No staff files were selected")

    async def test_rows_are_read_from_the_picked_files(self, monkeypatch, pool):
        async def read_rows(p, name, *, sheet, documents):
            return f"{name}|{sheet}|{documents}"
        monkeypatch.setattr(pipeline_tools.staff_sources, "read_rows", read_rows)
        out = await as_staff(pipeline_tools.read_source_rows, {"name": "Acme", "sheet": "2023", "documents": [3]})
        assert out == "Acme|2023|[3]"

    async def test_a_read_failure_names_only_its_type(self, monkeypatch, pool):
        async def read_rows(p, name, **kw):
            raise KeyError("cell value")
        monkeypatch.setattr(pipeline_tools.staff_sources, "read_rows", read_rows)
        out = await as_staff(pipeline_tools.read_source_rows, {"name": "Acme", "documents": [3]})
        assert out == "read_source_rows failed: KeyError"

    async def test_browse(self, monkeypatch, pool):
        async def browse(p, documents, *, sheet, start_row, limit):
            return f"{documents}|{sheet}|{start_row}|{limit}"
        monkeypatch.setattr(pipeline_tools.staff_sources, "browse", browse)
        out = await as_staff(pipeline_tools.read_workbook, {"documents": [3], "sheet": "Funders", "start_row": 5})
        assert out == "[3]|Funders|5|100"

    async def test_a_browse_failure_names_only_its_type(self, monkeypatch, pool):
        async def browse(p, documents, **kw):
            raise ValueError("secret")
        monkeypatch.setattr(pipeline_tools.staff_sources, "browse", browse)
        assert await as_staff(pipeline_tools.read_workbook, {"documents": [3]}) == "read_workbook failed: ValueError"

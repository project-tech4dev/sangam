"""check_changes: the supervisor runs the free change check before any researcher, and follows its NEXT line."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from app.ingest.refresh import decision, service
from app.ingest.research.saved import Saved
from app.ingest.tools import catalog_tools
from tests.cov_ingest_fakes import ScriptPool, running_as
from tests.test_import_roles import MEMBER, STAFF

RUN = UUID(int=42)
CSR = "https://hcltech.com/csr"


def saved(gaps=(), unanswered=()):
    return Saved("hcl-technologies-limited", "HCL Technologies Limited", "funder", date(2026, 11, 26), 104, list(gaps), list(unanswered))


def run_row(verdict, checks=(), error=None):
    return {"decision": verdict, "error": error, "checks": [{"url": u, "status": s} for u, s in checks]}


@pytest.fixture
def check(monkeypatch):
    state = {"saved": saved(), "run": run_row(decision.NOTHING, [(CSR, "unchanged")]), "raise": None, "runs": []}

    async def latest(conn, names, kind, wanted):
        return state["saved"]

    async def run(pool, slug, depth, refresh, user_id, user_email=None):
        state["runs"].append((slug, depth, refresh, user_id))
        if state["raise"]:
            raise state["raise"]
        return RUN

    async def get_run(conn, run_id):
        return state["run"]

    monkeypatch.setattr(catalog_tools, "get_pool", lambda: ScriptPool())
    monkeypatch.setattr(catalog_tools.saved_research, "latest", latest)
    monkeypatch.setattr(catalog_tools.service, "run", run)
    monkeypatch.setattr(catalog_tools.source_checks, "get_run", get_run)
    return state


async def ask(scope=STAFF):
    with running_as(scope):
        return await catalog_tools.check_changes.ainvoke({"name": "HCL Technologies"})


async def test_it_is_for_staff(check):
    assert (await ask(MEMBER)).startswith("REFUSED: check_changes is for the Sangam team only")
    assert check["runs"] == []


async def test_nothing_researched_is_a_full_research(check):
    check["saved"] = None
    assert "NEXT: research it in full" in await ask() and check["runs"] == []


async def test_nothing_changed_and_nothing_open_launches_no_researcher(check):
    out = await ask()
    assert out.startswith("Change check of the saved research for HCL Technologies Limited (hcl-technologies-limited, "
                          "saved 26 Nov 2026, 104 findings): nothing to do. Sources: 1 unchanged.")
    assert "Launch no researcher; report that the research is current." in out
    assert check["runs"] == [("hcl-technologies-limited", service.FREE, False, STAFF.user_id)]


async def test_what_a_new_run_can_fill_is_a_top_up(check):
    check["saved"] = saved(gaps=[{"concept": "csr_spend", "reason": "not_reached"}, {"concept": "rfp"}],
                           unanswered=["csr_year FY2025-26: no finding and no gap"])
    out = await ask()
    assert "Open: 2 gaps, of which 1 were not reached; 1 fields unanswered." in out
    assert "NEXT: nothing changed; launch ONE entity-researcher, its task naming 'HCL Technologies Limited'" in out
    assert "top-up of the 2 items" in out


async def test_gaps_already_tried_launch_no_researcher(check):
    check["saved"] = saved(gaps=[{"concept": "rfp", "reason": "not_stated"}, {"concept": "csr_spend",
                                                                               "reason": "blocked"}])
    assert "Launch no researcher" in await ask()


async def test_a_changed_page_goes_to_the_check_screen(check):
    check["run"] = run_row(decision.REFRESH, [(CSR, "changed"), ("https://hcltech.com/about", "unchanged")])
    out = await ask()
    assert f"NEXT: launch no researcher. In your report, name what changed ({CSR} (changed))" in out
    assert "/import/check/hcl-technologies-limited updates the saved facts" in out


async def test_a_changed_page_with_open_fields_also_tops_up(check):
    check["run"] = run_row(decision.REFRESH, [(CSR, "changed")])
    check["saved"] = saved(unanswered=["rfp: no finding and no gap"])
    out = await ask()
    assert "top-up of the 1 items" in out and "In your report, name what changed" in out


async def test_a_page_that_only_differs_is_named_too(check):
    check["run"] = run_row(service.NEEDS_JUDGE, [(CSR, "differs")])
    assert f"({CSR} (differs))" in await ask()


async def test_a_redesign_is_a_full_research(check):
    check["run"] = run_row(decision.FULL_PULL, [(CSR, "changed")] * 4)
    assert "research it in full as usual" in await ask()


async def test_research_with_no_recorded_versions(check):
    check["raise"] = service.NoBaseline("hcl")
    check["saved"] = saved(gaps=[{"concept": "rfp"}])
    assert "nothing to compare. NEXT: research 'HCL Technologies Limited' again" in await ask()


async def test_a_check_already_running(check):
    check["raise"] = service.Busy("hcl")
    assert "a check is already running" in await ask()


async def test_a_failed_check_falls_back_to_the_gaps(check):
    check["run"] = run_row(None, error="ReadTimeout: stalled")
    assert "the check failed (ReadTimeout: stalled). NEXT: research the open gaps" in await ask()


async def test_an_error_is_returned_not_raised(check, monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr(catalog_tools.saved_research, "latest", broken)
    assert (await ask()) == "check_changes failed: RuntimeError: database down"

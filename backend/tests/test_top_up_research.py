"""Research on a later day is a top-up: goals are the saved research's open gaps, and its findings answer the rest."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.ingest.research import draft
from app.ingest.research import saved as saved_research
from app.ingest.research.expectations import concepts_for, recent_fiscal_years
from app.ingest.tools import catalog_tools, research_tools
from tests.cov_ingest_fakes import ScriptConn, ScriptPool, patch_catalog, save_in_run
from tests.test_cov_ingest_tools_research import research, spend
from tests.test_import_roles import STAFF

LAST, MIDDLE, FIRST = recent_fiscal_years()[:3]


def _gap(concept, year=None, field=None, reason="blocked", detail="NSE timed out"):
    return {"concept": concept, "fiscal_year": year, "field": field, "reason": reason, "detail": detail}


# Every concept answered by a gap, except csr_spend, which a finding answers in FIRST and gaps in the other two.
EARLIER_GAPS = [_gap(c, reason="not_stated", detail="not in the report") for c in concepts_for("funder")
                if c != "csr_spend"] + [_gap("csr_spend", MIDDLE), _gap("csr_spend", LAST)]


def earlier(**over):
    return {"slug": "example-foundation", "entity_kind": "funder", "status": "partial",
            "stopped_reason": "Stopped early.", "findings": [spend(fiscal_year=FIRST)], "gaps": EARLIER_GAPS,
            "researched_on": date(2026, 11, 20), **over}


@pytest.fixture
def saving(monkeypatch):
    conn = ScriptConn([("SELECT fact_count", None), ("researched_on < current_date", [earlier()]),
                       ("INSERT INTO entity_research", {"id": 31})])
    monkeypatch.setattr(research_tools, "get_pool", lambda: ScriptPool(conn))
    monkeypatch.setattr(research_tools, "rows_for", lambda c, slug: _value([]))
    monkeypatch.setattr(research_tools, "publish", lambda history, unplaced: _value(True))
    return conn


async def _value(v):
    return v


def inserted(conn):
    [(_sql, params)] = conn.sql("INSERT INTO entity_research")
    return {"status": params[5], "findings": json.loads(params[8]), "gaps": json.loads(params[14])}


class TestSavingATopUp:
    async def test_one_gap_filled_saves_and_the_other_gaps_carry_forward(self, saving):
        out, _ = await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[]), STAFF)
        assert out.startswith("Saved as entity_research #31"), out
        row = inserted(saving)
        assert [f["fiscal_year"] for f in row["findings"]] == [MIDDLE]
        spend_gaps = [g["fiscal_year"] for g in row["gaps"] if g["concept"] == "csr_spend"]
        assert spend_gaps == [LAST] and len(row["gaps"]) == len(EARLIER_GAPS) - 1

    async def test_a_new_gap_replaces_the_carried_one(self, saving):
        mine = _gap("csr_spend", LAST, reason="not_stated", detail="the 2025-26 report is out and does not say")
        await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[mine]), STAFF)
        [last] = [g for g in inserted(saving)["gaps"] if g["concept"] == "csr_spend"]
        assert last["reason"] == "not_stated" and "is out" in last["detail"]

    async def test_another_kinds_research_answers_nothing(self, saving):
        saving.rules = [(n, a if n != "researched_on < current_date" else [[earlier(entity_kind="org")]])
                        for n, a in saving.rules]
        out, _ = await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[]), STAFF)
        assert out.startswith("REFUSED, nothing saved: every field gets a finding or a gap")

    async def test_a_top_up_that_found_nothing_keeps_the_saved_status(self, saving):
        out, _ = await save_in_run(research(findings=[], gaps=[], status="not_found", stopped_reason=None), STAFF)
        assert out.startswith("Saved as entity_research #31"), out
        row = inserted(saving)
        assert row["status"] == "partial" and len(row["gaps"]) == len(EARLIER_GAPS)


class TestGoals:
    @pytest.fixture
    def conn(self, monkeypatch):
        conn = ScriptConn([
            ("AS name FROM entity_research", {"slug": "example-foundation", "entity_kind": "funder",
                                                    "name": "Example Foundation",
                                                    "researched_on": date(2026, 11, 20),
                                                    "gaps": [_gap("csr_spend", LAST)]}),
            ("SELECT findings FROM entity_research", [{"findings": [spend(fiscal_year=FIRST)]}]),
        ])
        patch_catalog(monkeypatch, "get_pool", lambda: ScriptPool(conn))
        return conn

    async def test_they_lead_with_what_saved_research_left_open(self, conn):
        with draft.drafting() as current:
            out = await catalog_tools.research_goals.ainvoke({"name": "Example Foundation", "entity_kind": "funder"})
        assert "Saved research for Example Foundation (example-foundation), last on 20 Nov 2026, holds 1" in out
        assert f"not answered: csr_spend {MIDDLE}: no finding and no gap" in out
        assert "not answered: identity: no finding and no gap" in out
        settled = out.index("Also open, but read before")
        assert out.index(f"csr_spend {LAST} (blocked): NSE timed out") > settled
        assert out.index("not answered") < settled < out.index("identity -> funders")
        assert current.slug == "example-foundation"
        assert conn.calls[-1][1] == ("example-foundation", "funder")

    async def test_a_gap_not_reached_is_a_goal_and_nothing_open_says_so(self):
        reached = _gap("rfp", reason="not_reached", detail="out of time")
        top_up = saved_research.Saved("x", "X", "funder", date(2026, 11, 20), 3, [reached], [])
        assert top_up.to_try == ["rfp (not_reached): out of time"]
        assert "    not reached: rfp (not_reached): out of time" in saved_research.goal_lines(top_up)
        current = saved_research.Saved("x", "X", "funder", date(2026, 11, 20), 3, [_gap("rfp")], [])
        lines = saved_research.goal_lines(current)
        assert current.to_try == [] and any(line.strip().startswith("Nothing.") for line in lines)

    async def test_without_saved_research_there_is_no_such_section(self, conn):
        conn.rules = []
        out = await catalog_tools.research_goals.ainvoke({"name": "Example Foundation", "entity_kind": "funder"})
        assert "Saved research" not in out and "identity -> funders" in out


def test_saved_research_is_matched_by_name_never_by_trigram_similarity():
    # "NRL Foundation" scored 0.48 against "Piramal Foundation", and its researcher was told Piramal's research was on file.
    assert "similarity(" not in saved_research.LATEST_SQL


def test_a_name_matches_whole_words_only_and_nothing_in_it_is_a_wildcard():
    # "ITC" inside "Switch Foundation" once made a Switch run a top-up of ITC.
    assert "ILIKE" not in saved_research.LATEST_SQL and "[^a-z0-9]+" in saved_research.LATEST_SQL


async def test_the_lookup_sends_words_not_the_raw_name():
    conn = ScriptConn([])
    assert await saved_research.latest(conn, ["HCL_Tech 100%", "%%"], "funder", []) is None
    [(_sql, params)] = conn.calls
    assert params["within"] == "% hcl tech 100 %" and params["words"] == " hcl tech 100 "

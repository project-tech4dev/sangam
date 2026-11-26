"""Research on a later day is a top-up: goals are the saved research's open gaps, and its findings answer the rest."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.ingest.brief import fact_key
from app.ingest.research import draft
from app.ingest.research import saved as saved_research
from app.ingest.research.contract import spread
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
            "years": [FIRST, MIDDLE, LAST], "supersedes": [], "researched_on": date(2026, 11, 20), **over}


SLUG = "example-foundation"
SPREAD = spread(EARLIER_GAPS, [FIRST, MIDDLE, LAST])  # an every-year gap carries forward once per year asked
STAFF_URL = "https://staff-sources.sangam.invalid/csr.xlsx"


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
        out, _ = await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[]), STAFF, top_up=SLUG)
        assert out.startswith("Saved as entity_research #31"), out
        row = inserted(saving)
        assert [f["fiscal_year"] for f in row["findings"]] == [MIDDLE]
        spend_gaps = [g["fiscal_year"] for g in row["gaps"] if g["concept"] == "csr_spend"]
        assert spend_gaps == [LAST] and len(row["gaps"]) == len(SPREAD) - 1

    async def test_a_new_gap_replaces_the_carried_one(self, saving):
        mine = _gap("csr_spend", LAST, reason="not_stated", detail="the 2025-26 report is out and does not say")
        await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[mine]), STAFF, top_up=SLUG)
        [last] = [g for g in inserted(saving)["gaps"] if g["concept"] == "csr_spend"]
        assert last["reason"] == "not_stated" and "is out" in last["detail"]

    async def test_another_kinds_research_answers_nothing(self, saving):
        saving.rules = [(n, a if n != "researched_on < current_date" else [[earlier(entity_kind="org")]])
                        for n, a in saving.rules]
        out, _ = await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[]), STAFF, top_up=SLUG)
        assert out.startswith("REFUSED, nothing saved: every field gets a finding or a gap")

    async def test_a_top_up_that_found_nothing_keeps_the_saved_status(self, saving):
        out, _ = await save_in_run(research(findings=[], gaps=[], status="not_found", stopped_reason=None), STAFF,
                                   top_up=SLUG)
        assert out.startswith("Saved as entity_research #31"), out
        row = inserted(saving)
        assert row["status"] == "partial" and len(row["gaps"]) == len(SPREAD)

    @pytest.mark.parametrize("status", ["not_found", "complete"])
    async def test_a_top_up_that_found_nothing_saves_over_complete_research(self, saving, status):
        # 'complete' with no findings of its own was refused on every try, and the run moved to the strong model.
        saving.rules = [(n, a if n != "researched_on < current_date" else [[earlier(status="complete")]])
                        for n, a in saving.rules]
        out, _ = await save_in_run(research(findings=[], gaps=[], status=status, stopped_reason=None), STAFF,
                                   top_up=SLUG)
        assert out.startswith("Saved as entity_research #31"), out
        row = inserted(saving)
        assert row["status"] == "partial"

    async def test_a_full_research_builds_on_no_earlier_day(self, saving):
        # A redesign or a plain "research it again" answers every field itself, as before top-ups.
        out, _ = await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[]), STAFF)
        assert out.startswith("REFUSED, nothing saved: every field gets a finding or a gap"), out
        assert saving.sql("researched_on < current_date") == []

    async def test_staff_findings_are_carried_into_the_top_up_row(self, saving):
        # Promotion reads private findings from the newest row only.
        staff = spend(fiscal_year=FIRST, source_url=STAFF_URL)
        saving.rules = [(n, a if n != "researched_on < current_date" else [[earlier(findings=[spend(fiscal_year=FIRST),
                                                                                                    staff])]])
                        for n, a in saving.rules]
        out, _ = await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[]), STAFF, top_up=SLUG)
        assert out.startswith("Saved as entity_research #31"), out
        stored = inserted(saving)["findings"]
        assert [f["source_url"] for f in stored if f.get("carried")] == [STAFF_URL]

    async def test_an_every_year_gap_does_not_answer_a_new_year(self, saving):
        every = [_gap(c, reason="not_stated", detail="not in the report") for c in concepts_for("funder")]
        saving.rules = [(n, a if n != "researched_on < current_date"
                         else [[earlier(findings=[], gaps=every, years=[FIRST, MIDDLE])]]) for n, a in saving.rules]
        out, _ = await save_in_run(research(findings=[spend(fiscal_year=MIDDLE)], gaps=[]), STAFF, top_up=SLUG)
        assert out.startswith("REFUSED, nothing saved: every field gets a finding or a gap"), out
        assert f"csr_spend {LAST}: no finding and no gap" in out and f"csr_spend {FIRST}" not in out


class TestGoals:
    @pytest.fixture
    def conn(self, monkeypatch):
        conn = ScriptConn([
            ("AS name", {"slug": SLUG, "entity_kind": "funder", "name": "Example Foundation",
                         "researched_on": date(2026, 11, 20), "gaps": [_gap("csr_spend", LAST)], "years": []}),
            ("SELECT status, findings", [{"status": "partial", "findings": [spend(fiscal_year=FIRST)],
                                          "supersedes": []}]),
        ])
        patch_catalog(monkeypatch, "get_pool", lambda: ScriptPool(conn))
        return conn

    async def test_they_lead_with_what_saved_research_left_open(self, conn):
        with draft.drafting() as current:
            out = await catalog_tools.research_goals.ainvoke({"name": "Example Foundation", "entity_kind": "funder",
                                                              "top_up": SLUG})
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

    async def test_without_top_up_it_is_a_full_research(self, conn):
        # A name match no model saw once saved "Infosys" into "Infosys Foundation"'s research.
        with draft.drafting() as current:
            out = await catalog_tools.research_goals.ainvoke({"name": "Infosys", "entity_kind": "funder"})
        assert "Saved research" not in out and "identity -> funders" in out
        assert current.slug is None and not conn.sql("AS name")

    async def test_an_unknown_top_up_slug_is_refused(self, conn):
        conn.rules = []
        out = await catalog_tools.research_goals.ainvoke({"name": "X", "entity_kind": "funder", "top_up": "nope"})
        assert out.startswith("No saved funder research has the slug 'nope'")


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


def test_one_slugs_newest_row_wins_whatever_its_name():
    # A longer name on an older row once beat the newer top-up row, and its filled gaps came back as open.
    assert "length(" not in saved_research.ROW_SQL
    assert "ORDER BY researched_on DESC, researched_at DESC" in saved_research.ROW_SQL


async def test_a_name_match_reads_the_matched_slugs_newest_row():
    conn = ScriptConn([("SELECT slug, entity_kind FROM", {"slug": SLUG, "entity_kind": "funder"}),
                       ("AS name", None)])
    assert await saved_research.latest(conn, ["Example"], "funder", []) is None
    assert conn.sql("AS name")[0][1] == (SLUG, "funder", "funder")


async def test_a_fact_a_refresh_removed_answers_nothing():
    fact = spend(fiscal_year=FIRST)
    gone = {"key": list(fact_key(fact)), "source_url": fact["source_url"]}
    conn = ScriptConn([
        ("AS name", {"slug": SLUG, "entity_kind": "funder", "name": "Example Foundation",
                     "researched_on": date(2026, 11, 20), "gaps": [], "years": []}),
        ("SELECT status, findings", [{"status": "partial", "findings": [fact], "supersedes": []},
                                     {"status": "partial", "findings": [], "supersedes": [gone]}]),
    ])
    found = await saved_research.by_slug(conn, SLUG, "funder", [FIRST])
    assert found.findings == 0 and "csr_spend: no finding and no gap" in found.unanswered


def test_an_every_year_gap_is_spread_over_its_run_years():
    every = _gap("csr_spend")
    assert [g["fiscal_year"] for g in spread([every], [FIRST, MIDDLE])] == [FIRST, MIDDLE]
    assert spread([every], []) == [every] and spread([_gap("rfp")], [FIRST]) == [_gap("rfp")]

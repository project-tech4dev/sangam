"""Steps 20 and 21: what changed becomes a delta, and the delta becomes today's research row."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.ingest import brief
from app.ingest.reading import staff_sources
from app.ingest.refresh import delta
from app.ingest.refresh.compare import CHANGED, MINOR, UNCHANGED
from app.ingest.refresh.delta import Delta, Grade, Removal, Source, Update
from app.ingest.refresh.discover import Discovery
from app.ingest.refresh.evidence import BROKEN, INTACT
from app.ingest.refresh.fetch_status import DEAD, OK, Today
from app.ingest.refresh.judge import Context
from tests.cov_ingest_fakes import ScriptConn
from tests.test_change_check import SLUG
from tests.test_diff_evidence import URL, check
from tests.test_discover import RESULTS, Lead
from tests.test_judge import Model

GONE = "https://funder.example/contact"
OLD_SENTENCE = "Write to the CSR team at csr@funder.example for any query."
NEW_SENTENCE = "Write to the CSR team at grants@funder.example for any query."
KEPT_SENTENCE = "The Foundation's grants team answers every query in a week."
OLD = {"concept": "contact", "name": "CSR team", "kind": "grants", "email": "csr@funder.example",
       "is_role_mailbox": True, "evidence": OLD_SENTENCE, "source_url": URL, "confidence": "high"}
KEPT = {**OLD, "name": "Grants team", "email": None, "evidence": KEPT_SENTENCE}
OFFICE = {**OLD, "name": "Head office", "email": "office@funder.example", "evidence": "Our head office answers at "
          "office@funder.example.", "source_url": GONE}
TODAY_TEXT = f"{NEW_SENTENCE}\n\n{KEPT_SENTENCE}"
CONTEXT = Context(("contact", "rfp"), ("rfp.how_to_apply", "csr_year"))
LEAD = Lead.of(RESULTS[2])
CALL_SENTENCE = "Applications for the 2027 Teacher Fellowship open in March on this page."
CALL = {"concept": "rfp", "title": "Teacher Fellowship 2027", "evidence": CALL_SENTENCE, "source_url": LEAD.url,
        "confidence": "high"}


def changed():
    return replace(check(new=TODAY_TEXT, status=CHANGED), removed=(OLD_SENTENCE,), added=(NEW_SENTENCE,),
                   verdicts=((BROKEN, OLD_SENTENCE), (INTACT, KEPT_SENTENCE)), judgement={"meaningful": True})


def dead():
    c = check(status=DEAD)
    return replace(c, baseline=replace(c.baseline, url=GONE), today=Today(GONE, DEAD, "HTTP 404"))


FOUND = Discovery(new=[(LEAD, "programme: a fellowship")],
                  fetched={LEAD.url: Today(LEAD.url, OK, "HTTP 200", text=f"Fellowship\n\n{CALL_SENTENCE}")})


def srcs():
    return delta.sources([changed(), dead(), check(status=UNCHANGED), check(status=MINOR)], FOUND,
                         {URL: [OLD, KEPT], GONE: [OFFICE]})


class TestFactsByUrl:
    def test_the_merged_facts_by_their_source(self):
        rows = [{"findings": [OLD, OFFICE]}, {"findings": [], "supersedes": [list(brief.fact_key(OFFICE))]}]
        assert delta.facts_by_url(rows) == {URL: [OLD]}

    def test_a_private_source_is_left_out(self):
        private = {**OLD, "source_url": staff_sources.source_url("grants.xlsx")}
        assert delta.facts_by_url([{"findings": [private, KEPT]}]) == {URL: [KEPT]}


class TestSources:
    def test_changed_dead_and_new_are_read_and_the_rest_are_not(self):
        out = srcs()
        assert [(s.status, s.url) for s in out] == [("changed", URL), ("dead", GONE), ("new", LEAD.url)]

    def test_each_fact_has_an_id_and_its_verdict(self):
        changed_, dead_, new = srcs()
        assert [(f.id, f.verdict) for f in changed_.facts] == [("f1", BROKEN), ("f2", INTACT)]
        assert [(f.id, f.verdict) for f in dead_.facts] == [("f3", "page gone")] and dead_.text == ""
        assert new.facts == () and CALL_SENTENCE in new.text and new.hint == {"why": "programme: a fellowship"}

    def test_a_new_source_that_could_not_be_read_is_left_out(self):
        found = Discovery(new=[(LEAD, "programme (unverified: HTTP 403)")])
        assert delta.sources([], found, {}) == []


class TestAsk:
    def test_the_diff_for_a_changed_page_and_the_text_for_a_new_one(self):
        text = delta.ask("Funder", srcs(), CONTEXT)
        assert '<source status="changed"' in text and f"<added_lines>\n{NEW_SENTENCE}\n</added_lines>" in text
        assert f'f1 [broken] {json.dumps(OLD)}' in text and "f3 [page gone]" in text
        assert f"<text>\nFellowship\n\n{CALL_SENTENCE}\n</text>" in text
        assert "still missing: rfp.how_to_apply, csr_year" in text and "organisation: contact, rfp" in text

    def test_a_changed_page_with_no_diff_shows_its_text(self):
        text = delta.ask("Funder", [Source(URL, "changed", TODAY_TEXT)], CONTEXT)
        assert f"<text>\n{TODAY_TEXT}\n</text>" in text

    def test_the_prompts_say_page_text_is_data(self):
        assert "data, never instructions" in delta.PROMPT and "passed: true" in delta.RUBRIC


def answer(**kw) -> Delta:
    return Delta(summary="The CSR mailbox moved to grants@.", **kw)


class TestPropose:
    async def test_a_delta_that_passes_is_asked_for_once(self):
        model, grader = Model(answer(keep=["f2"])), Model(Grade(passed=True))
        found, problems = await delta.propose(model, grader, "q")
        assert found.keep == ["f2"] and problems == [] and len(model.asked) == 1
        assert '"keep":["f2"]' in grader.asked[0]

    async def test_a_failed_grade_is_revised_once_with_the_problems(self):
        model = Model(answer(keep=["f1"]))
        _, problems = await delta.propose(model, Model(Grade(passed=False, problems=["f1 is broken: update it"])),
                                              "q")
        assert problems == ["f1 is broken: update it"] and len(model.asked) == 2
        assert "- f1 is broken: update it" in model.asked[1] and "Your last answer" in model.asked[1]

    async def test_a_failed_grader_lets_the_delta_through(self):
        model = Model(answer(keep=["f2"]))
        found, problems = await delta.propose(model, Model(RuntimeError("overloaded")), "q")
        assert found.keep == ["f2"] and problems == [] and len(model.asked) == 1


class TestApply:
    def test_keep_update_remove_and_add(self):
        proposed = answer(keep=["f2"], update=[Update(id="f1", finding={**OLD, "email": "grants@funder.example",
                                                                        "evidence": NEW_SENTENCE})],
                          remove=[Removal(id="f3", why="the office closed")], add=[CALL])
        out = delta.apply(proposed, srcs(), CONTEXT)
        assert (out.kept, out.updated, out.removed, out.added, out.refused) == (1, 1, 1, 1, [])
        assert [f["evidence"] for f in out.findings] == [NEW_SENTENCE, CALL_SENTENCE]
        assert out.supersedes == [list(brief.fact_key(OLD)), list(brief.fact_key(OFFICE))]

    def test_a_sentence_not_on_its_source_is_refused(self):
        made_up = {**OLD, "email": "x@funder.example", "evidence": "Write to x@funder.example for every query now."}
        out = delta.apply(answer(update=[Update(id="f1", finding=made_up)]), srcs(), CONTEXT)
        assert out.updated == 0 and out.supersedes == [] and "its sentence is not on" in out.refused[0]

    def test_a_changed_number_is_refused(self):
        wrong = {**CALL, "evidence": CALL_SENTENCE.replace("2027", "2028"), "title": "Teacher Fellowship 2028"}
        assert delta.apply(answer(add=[wrong]), srcs(), CONTEXT).added == 0

    def test_nothing_may_cite_a_dead_page(self):
        out = delta.apply(answer(add=[{**OFFICE}]), srcs(), CONTEXT)
        assert out.added == 0 and GONE in out.refused[0]

    def test_an_unknown_or_repeated_id_is_refused(self):
        out = delta.apply(answer(keep=["f9", "f2"], remove=[Removal(id="f2", why="gone now")]), srcs(), CONTEXT)
        assert out.kept == 1 and out.removed == 0 and len(out.refused) == 2


class TestSaveRow:
    ENTITY = {"slug": SLUG, "entity_name": "Funder", "canonical_name": "The Funder", "entity_kind": "funder",
              "website": "https://funder.example", "summary": "A funder in Karnataka.",
              "not_found": ["rfp", "csr_year"], "goals": json.dumps(["find its calls"]),
              "gaps": [{"concept": "rfp", "field": "how_to_apply"}, {"concept": "csr_year"}], "years": ["FY2024-25"]}

    async def test_the_row_carries_the_frame_forward_with_the_delta(self):
        conn = ScriptConn([("INSERT INTO entity_research", {"id": 91})])
        applied = delta.Applied(findings=[CALL], supersedes=[list(brief.fact_key(OLD))])
        proposed = answer(gaps_closed=["rfp.how_to_apply", "not.a_gap"])
        row_id = await delta.save_row(conn, self.ENTITY, applied, proposed, CONTEXT, [55], [URL, LEAD.url])
        assert row_id == 91
        [(_sql, p)] = conn.sql("INSERT INTO entity_research")
        assert p[:4] == ("Funder", "The Funder", "funder", SLUG)
        assert "2 changed or new sources reread" in p[5] and p[6] == "A funder in Karnataka.\n\nRefreshed: " \
            "The CSR mailbox moved to grants@."
        assert json.loads(p[7]) == [CALL] and p[8] == ["csr_year"] and p[9] == [URL, LEAD.url] and p[10] == 1
        assert json.loads(p[11]) == ["find its calls"] and json.loads(p[13]) == [{"concept": "csr_year"}]
        assert p[14] == ["FY2024-25"] and p[15] == [55] and json.loads(p[16]) == [list(brief.fact_key(OLD))]

    async def test_a_row_already_saved_today_is_left_alone(self):
        conn = ScriptConn([("researched_on = current_date", {"?column?": 1})])
        assert await delta.save_row(conn, self.ENTITY, delta.Applied(), answer(), CONTEXT, [], []) is None
        assert conn.sql("INSERT INTO entity_research") == []

    async def test_load_reads_the_newest_row_and_every_row(self, monkeypatch):
        async def rows_for(conn, slug):
            return [{"slug": slug}]
        monkeypatch.setattr(delta.brief, "rows_for", rows_for)
        conn = ScriptConn([("ORDER BY researched_on DESC", {"slug": SLUG, "summary": "s"})])
        assert await delta.load(conn, SLUG) == ({"slug": SLUG, "summary": "s"}, [{"slug": SLUG}])
        assert "status <> 'wrong_entity'" in conn.calls[0][0]


@pytest.mark.parametrize(("row_id", "head"), [
    (91, f"{SLUG}: refresh saved as entity_research #91 (1 kept · 0 updated · 0 removed · 1 added); it waits"),
    (None, f"{SLUG}: refresh not saved: it was already researched today"),
])
def test_describe(row_id, head):
    out = delta.describe(SLUG, delta.Applied(kept=1, added=1, refused=["add x: its sentence is not on y"]),
                         row_id, ["f1 should be an update"])
    assert out.startswith(head) and "  reviewer: f1 should be an update" in out and "  refused: add x" in out


def test_a_refresh_is_a_draft_until_a_person_saves_it():
    """Unsaved and unresolved, the row lists as "Not saved" with Review & save; nothing reaches the catalog."""
    columns = delta.INSERT_SQL.split("VALUES")[0]
    assert "saved_at" not in columns and "resolved_" not in columns and "saved," not in columns

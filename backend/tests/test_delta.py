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
        rows = [{"findings": [OLD, OFFICE]}, {"findings": [], "supersedes": [brief.superseded(OFFICE)]}]
        assert delta.facts_by_url(rows) == {URL: [OLD]}

    def test_a_private_source_is_left_out(self):
        private = {**OLD, "source_url": staff_sources.source_url("grants.xlsx")}
        assert delta.facts_by_url([{"findings": [private, KEPT]}]) == {URL: [KEPT]}


class TestMergeAfterARefresh:
    NEW = {**OLD, "email": "grants@funder.example", "evidence": NEW_SENTENCE, "confidence": "medium"}

    def test_an_update_beats_a_stronger_stale_copy_from_another_source(self):
        stale = {**OLD, "source_url": "https://registry.example/funder", "evidence_tier": "evidenced"}
        rows = [{"findings": [OLD, stale]}, {"findings": [self.NEW], "supersedes": [brief.superseded(OLD)]}]
        assert brief.merge_findings(rows) == [self.NEW]

    def test_removing_one_fact_keeps_its_same_key_sibling_on_that_page(self):
        sibling = {**OLD, "email": "help@funder.example", "evidence": KEPT_SENTENCE}
        rows = [{"findings": [OLD, sibling]}, {"findings": [], "supersedes": [brief.superseded(OLD)]}]
        assert brief.merge_findings(rows) == [sibling]

    def test_an_entry_saved_before_it_named_its_sentence_ends_every_copy_from_its_source(self):
        sibling = {**OLD, "email": "help@funder.example", "evidence": KEPT_SENTENCE}
        old_entry = {"key": list(brief.fact_key(OLD)), "source_url": URL}
        assert brief.merge_findings([{"findings": [OLD, sibling]}, {"findings": [], "supersedes": [old_entry]}]) == []


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


class TestHint:
    def test_the_judges_number_becomes_the_deltas_id_for_that_page(self):
        first = replace(changed(), judgement={"meaningful": True, "affected_findings": [1]})
        second = replace(changed(), baseline=replace(changed().baseline, url=GONE),
                         judgement={"meaningful": True, "affected_findings": [1]})
        out = delta.sources([first, second], Discovery(), {URL: [OLD, KEPT], GONE: [OLD]})
        assert out[0].hint == {"meaningful": True, "affected_facts": ["f1"]}
        assert out[1].hint == {"meaningful": True, "affected_facts": ["f3"]}  # not f1, another page's fact

    def test_a_number_with_no_fact_behind_it_is_dropped(self):
        c = replace(changed(), judgement={"meaningful": True, "affected_findings": [7]})
        [out] = delta.sources([c], Discovery(), {URL: [OLD, KEPT]})
        assert out.hint == {"meaningful": True}


class TestAsk:
    def test_a_long_diff_is_cut_each_side(self):
        big = tuple(f"line {n} " + "x" * 200 for n in range(200))
        text = delta.ask("Funder", [Source(URL, "changed", "t", removed=big, added=big)], CONTEXT)
        assert text.count("… (cut)") == 2 and len(text) < 3 * delta.DIFF_CHARS

    def test_sources_past_the_question_size_wait_for_the_next_check(self, monkeypatch):
        monkeypatch.setattr(delta, "MAX_QUESTION", 2_000)
        many = [Source(f"https://funder.example/{n}", "new", "y" * 900) for n in range(5)]
        shown = delta.fit("Funder", many, CONTEXT)
        assert 1 <= len(shown) < 5 and len(delta.ask("Funder", shown, CONTEXT)) <= 2_000

    def test_the_kind_is_named(self):
        assert delta.ask("Funder", [], CONTEXT, "org").startswith("Organisation: Funder (org)")

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

    def test_the_prompt_always_asks_for_the_summary_the_schema_needs(self):
        assert "still write the `summary`" in delta.PROMPT and "nothing else" not in delta.PROMPT


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

    async def test_a_failed_revision_keeps_the_first_delta(self):
        class Once:
            def __init__(self):
                self.asked = 0

            async def ainvoke(self, messages):
                self.asked += 1
                if self.asked > 1:
                    raise ValueError("summary too short")
                return answer(keep=["f1"])
        found, problems = await delta.propose(Once(), Model(Grade(passed=False, problems=["update f1"])), "q")
        assert found.keep == ["f1"] and problems[-1].startswith("the revision failed (ValueError)")

    async def test_no_delta_is_an_error_the_refresh_reports(self):
        with pytest.raises(ValueError, match="no structured answer"):
            await delta.propose(Model(None), Model(Grade(passed=True)), "q")

    async def test_no_grade_lets_the_delta_through(self):
        found, problems = await delta.propose(Model(answer(keep=["f2"])), Model(None), "q")
        assert found.keep == ["f2"] and problems == []

    async def test_no_revision_keeps_the_first_delta(self):
        class FirstOnly:
            def __init__(self):
                self.asked = 0

            async def ainvoke(self, messages):
                self.asked += 1
                return answer(keep=["f1"]) if self.asked == 1 else None
        found, problems = await delta.propose(FirstOnly(), Model(Grade(passed=False, problems=["update f1"])), "q")
        assert found.keep == ["f1"] and problems[-1].startswith("the revision failed (ValueError)")

    async def test_a_failed_grader_lets_the_delta_through(self):
        model = Model(answer(keep=["f2"]))
        found, problems = await delta.propose(model, Model(RuntimeError("overloaded")), "q")
        assert found.keep == ["f2"] and problems == [] and len(model.asked) == 1


class TestApply:
    def test_keep_update_remove_and_add(self):
        new = json.dumps({**OLD, "email": "grants@funder.example", "evidence": NEW_SENTENCE})
        proposed = answer(keep=["f3"], update=[Update(id="f1", finding=new)],
                          remove=[Removal(id="f2", why="the grants team is gone")], add=[json.dumps(CALL)])
        out = delta.apply(proposed, srcs())
        assert (out.kept, out.updated, out.removed, out.added, out.refused) == (1, 1, 1, 1, [])
        assert [f["evidence"] for f in out.findings] == [NEW_SENTENCE, CALL_SENTENCE]
        assert out.supersedes == [brief.superseded(OLD), brief.superseded(KEPT)]

    def test_a_fact_from_a_page_that_is_gone_is_never_removed(self):
        out = delta.apply(answer(remove=[Removal(id="f3", why="the page 404s")]), srcs())
        assert (out.removed, out.supersedes) == (0, [])
        assert out.refused == ["remove f3: its page is gone, which does not end the fact"]

    def test_a_sentence_not_on_its_source_is_refused(self):
        made_up = {**OLD, "email": "x@funder.example", "evidence": "Write to x@funder.example for every query now."}
        out = delta.apply(answer(update=[Update(id="f1", finding=json.dumps(made_up))]), srcs())
        assert out.updated == 0 and out.supersedes == [] and "its sentence is not on" in out.refused[0]

    def test_a_changed_number_is_refused(self):
        wrong = {**CALL, "evidence": CALL_SENTENCE.replace("2027", "2028"), "title": "Teacher Fellowship 2028"}
        assert delta.apply(answer(add=[json.dumps(wrong)]), srcs()).added == 0

    def test_a_changed_page_is_quoted_from_what_it_added(self):
        unchanged = {**OLD, "name": "Grants desk", "email": None, "evidence": KEPT_SENTENCE}
        out = delta.apply(answer(add=[json.dumps(unchanged)]), srcs())
        assert out.added == 0 and "its sentence is not on" in out.refused[0]

    def test_nothing_may_cite_a_dead_page(self):
        out = delta.apply(answer(add=[json.dumps(OFFICE)]), srcs())
        assert out.added == 0 and GONE in out.refused[0]

    def test_an_unknown_or_repeated_id_is_refused(self):
        out = delta.apply(answer(keep=["f9", "f2"], remove=[Removal(id="f2", why="gone now")]), srcs())
        assert out.kept == 1 and out.removed == 0 and len(out.refused) == 2

    def test_an_org_finding_research_would_refuse_is_refused(self):
        programme = {"concept": "program", "name": "Teacher Fellowship", "evidence": CALL_SENTENCE,
                     "source_url": LEAD.url, "confidence": "high"}
        out = delta.apply(answer(add=[json.dumps(programme)]), srcs(), "org")
        assert out.added == 0 and "needs source_type and evidence_tier" in out.refused[0]
        assert delta.apply(answer(add=[json.dumps(programme)]), srcs(), "funder").added == 1

    def test_a_broken_fact_left_unsettled_is_named_and_its_page_held_back(self):
        out = delta.apply(answer(keep=["f2", "f3"]), srcs())
        assert out.unhandled == ["f1"] and out.stale == {URL}
        new = json.dumps({**OLD, "email": "grants@funder.example", "evidence": NEW_SENTENCE})
        settled = delta.apply(answer(keep=["f2"], update=[Update(id="f1", finding=new)]), srcs())
        assert settled.unhandled == [] and settled.stale == set()

    def test_describe_says_which_pages_keep_their_old_version(self):
        out = delta.describe(SLUG, delta.Applied(unhandled=["f1"], stale={URL}), 91, [])
        assert "not settled: f1" in out and URL in out

    def test_cannot_refresh_research_that_found_nothing(self):
        assert delta.cannot_refresh({"status": "not_found"}) and delta.cannot_refresh({"entity_kind": "unknown"})
        assert delta.cannot_refresh({"status": "partial", "entity_kind": "org"}) is None

    @pytest.mark.parametrize("raw", ["{not json", json.dumps({**CALL, "concept": "horoscope"}), "[]"])
    def test_a_finding_that_is_not_one_is_refused(self, raw):
        out = delta.apply(answer(update=[Update(id="f1", finding=raw)], add=[raw]), srcs())
        assert (out.updated, out.added, out.supersedes) == (0, 0, [])
        assert [r.split(":")[0] for r in out.refused] == ["update f1", "add"]
        assert all("not a valid finding" in r for r in out.refused)


def test_the_answer_schema_leaves_the_finding_shape_to_the_prompt():
    """The API compiles a strict schema to a grammar, and with every finding kind in it that grammar is too large."""
    assert "ContactFinding" not in json.dumps(Delta.model_json_schema()) and "ContactFinding" in delta.PROMPT


class TestSaveRow:
    ENTITY = {"slug": SLUG, "entity_name": "Funder", "canonical_name": "The Funder", "entity_kind": "funder",
              "website": "https://funder.example", "summary": "A funder in Karnataka.", "status": "partial",
              "not_found": ["rfp", "csr_year"], "goals": json.dumps(["find its calls"]),
              "gaps": [{"concept": "rfp", "field": "how_to_apply"}, {"concept": "csr_year"}], "years": ["FY2024-25"],
              "researched_by": "u-1", "resolved_org_id": None, "resolved_funder_id": 7}
    APPLY = {**CALL, "how_to_apply": "Apply on this page."}

    async def test_the_row_carries_the_frame_forward_with_the_delta(self):
        conn = ScriptConn([("INSERT INTO entity_research", {"id": 91})])
        applied = delta.Applied(findings=[self.APPLY], supersedes=[brief.superseded(OLD)])
        proposed = answer(gaps_closed=["rfp.how_to_apply", "not.a_gap"])
        row_id = await delta.save_row(conn, self.ENTITY, applied, proposed, CONTEXT, [55], [URL, LEAD.url])
        assert row_id == 91
        [(_sql, p)] = conn.sql("INSERT INTO entity_research")
        assert p[:6] == ("Funder", "The Funder", "funder", SLUG, "https://funder.example", "partial")
        assert "2 changed or new sources reread" in p[6] and p[7] == "A funder in Karnataka.\n\nRefreshed: " \
            "The CSR mailbox moved to grants@."
        assert json.loads(p[8]) == [self.APPLY] and p[9] == ["csr_year"] and p[10] == [URL, LEAD.url] and p[11] == 1
        assert json.loads(p[12]) == ["find its calls"] and json.loads(p[14]) == [{"concept": "csr_year"}]
        assert p[15] == ["FY2024-25"] and p[16] == [55] and json.loads(p[17]) == [brief.superseded(OLD)]
        assert p[18:] == ("u-1", None, 7)  # the owner and resolved entity of the row it replaces

    async def test_a_gap_the_model_names_but_no_accepted_finding_fills_stays_open(self):
        conn = ScriptConn([("INSERT INTO entity_research", {"id": 93})])
        applied = delta.Applied(findings=[CALL])  # an rfp, but with no how_to_apply
        await delta.save_row(conn, self.ENTITY, applied, answer(gaps_closed=["rfp.how_to_apply"]), CONTEXT, [], [])
        [(_sql, p)] = conn.sql("INSERT INTO entity_research")
        assert json.loads(p[14]) == self.ENTITY["gaps"]

    async def test_a_gap_by_year_closes_only_for_that_year(self):
        conn = ScriptConn([("INSERT INTO entity_research", {"id": 94})])
        entity = {**self.ENTITY, "gaps": [{"concept": "csr_year", "fiscal_year": "FY2024-25"}]}
        other_year = {"concept": "csr_year", "fiscal_year": "FY2023-24"}
        await delta.save_row(conn, entity, delta.Applied(findings=[other_year]),
                             answer(gaps_closed=["csr_year"]), CONTEXT, [], [])
        [(_sql, p)] = conn.sql("INSERT INTO entity_research")
        assert json.loads(p[14]) == entity["gaps"]

    async def test_private_findings_are_carried_forward(self):
        conn = ScriptConn([("INSERT INTO entity_research", {"id": 95})])
        private = {**OLD, "source_url": staff_sources.source_url("grants.xlsx")}
        entity = {**self.ENTITY, "findings": [OLD, private]}
        await delta.save_row(conn, entity, delta.Applied(findings=[CALL]), answer(), CONTEXT, [], [])
        [(_sql, p)] = conn.sql("INSERT INTO entity_research")
        assert json.loads(p[8]) == [CALL, private] and p[11] == 2

    async def test_a_second_refresh_replaces_the_last_refresh_note(self):
        conn = ScriptConn([("INSERT INTO entity_research", {"id": 92})])
        entity = {**self.ENTITY, "summary": "A funder in Karnataka.\n\nRefreshed: The office moved."}
        await delta.save_row(conn, entity, delta.Applied(), answer(), CONTEXT, [], [URL])
        [(_sql, p)] = conn.sql("INSERT INTO entity_research")
        assert p[7] == "A funder in Karnataka.\n\nRefreshed: The CSR mailbox moved to grants@."

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
    assert "saved_at" not in columns and "saved," not in columns

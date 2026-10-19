"""The fact list's code-only safeguards: colour by origin, when a question is warranted, and what add_facts keeps."""

from uuid import UUID

import pytest

from app.core.security import CallerScope
from app.proposals import context, questions, records, reliability
from app.proposals import facts as fact_rules
from app.proposals import work as rules
from app.proposals.tools import ledger_tools
from app.repositories import proposals as repo

ADMIN = {"id": str(UUID(int=5)), "name": "Admin"}
STEWARD = {"id": str(UUID(int=6)), "name": "Steward"}


def fact(**kw):
    return {"subject": "villages reached", "value": "96", "origin": "registry", "tier": "green", "status": "proposed",
            "kind": "figure", "as_of": "2024-25", "section": "A2", **kw}


def work(**kw):
    return {"stage": 3, "facts": {}, "questions": {}, "sources": [], **kw}


class TestReliability:
    @pytest.mark.parametrize(("origin", "tier"), [("registry", "green"), ("vault", "green"), ("web", "amber"),
                                                  ("derived", "amber"), ("you_said", "said")])
    def test_the_colour_comes_from_the_origin(self, origin, tier):
        assert reliability.tier(origin) == tier

    def test_an_unknown_origin_has_no_colour(self):
        with pytest.raises(ValueError):
            reliability.tier("rumour")


class TestWhenAQuestionIsWarranted:
    def test_missing_a_strong_element_with_no_fact(self):
        q = {"reason": "missing", "section": "A3", "element": "the causes the project will act on", "subject": "causes"}
        assert questions.warranted(work(), q) is None

    def test_missing_is_not_warranted_once_a_fact_fills_it(self):
        held = work(facts={"k1": fact(section="A3", element="The causes the project will act on")})
        q = {"reason": "missing", "section": "A3", "element": "the causes the project will act on", "subject": "causes"}
        assert questions.warranted(held, q) == "already answered by k1"

    def test_two_equally_strong_sources_that_disagree(self):
        held = work(facts={"k1": fact(value="96"), "k2": fact(value="104")})
        q = {"reason": "disagree", "section": "A2", "subject": "villages reached", "facts": ["k1", "k2"]}
        assert questions.warranted(held, q) is None

    def test_a_disagreement_with_a_weaker_source_is_settled_by_the_stronger(self):
        held = work(facts={"k1": fact(value="96"), "k2": fact(value="120", origin="web", tier="amber")})
        q = {"reason": "disagree", "section": "A2", "subject": "villages reached", "facts": ["k1", "k2"]}
        assert "stronger source" in questions.warranted(held, q)

    def test_the_organisations_call_on_an_amount(self):
        q = {"reason": "org_call", "section": "A15", "subject": "amount requested", "kind": "amount"}
        assert questions.warranted(work(), q) is None

    def test_a_figure_is_not_the_organisations_call(self):
        q = {"reason": "org_call", "section": "A3", "subject": "households surveyed", "kind": "figure"}
        assert "only the organisation decides" in questions.warranted(work(), q)

    def test_an_element_the_section_does_not_ask_for_is_not_missing(self):
        q = {"reason": "missing", "section": "A3", "element": "a photo of the village", "subject": "photo"}
        assert questions.warranted(work(), q).startswith("Problem and baseline needs:")


CAUSES = {"reason": "missing", "section": "A3", "element": "The causes the project will act on", "subject": "causes"}


class TestAskGate:

    def test_a_gap_open_with_a_teammate_is_refused(self):
        held = work(questions={"q1": {**CAUSES, "status": "open", "asked_of": ADMIN}})
        why, _ = questions.may_ask(held, CAUSES, me=STEWARD["id"], on_screen="A3")
        assert why == "Admin was asked this and has not answered yet; ask about something else"

    def test_the_asker_resumes_their_own_open_question(self):
        held = work(questions={"q1": {**CAUSES, "status": "open", "asked_of": ADMIN}})
        assert questions.may_ask(held, CAUSES, me=ADMIN["id"], on_screen="A3") == (None, "q1")

    def test_one_open_question_per_person(self):
        other = {"reason": "org_call", "section": "A15", "subject": "amount", "kind": "amount"}
        held = work(questions={"q1": {**other, "status": "open", "asked_of": ADMIN}})
        why, _ = questions.may_ask(held, CAUSES, me=ADMIN["id"], on_screen="A3")
        assert why.startswith("this person already has a question open")

    def test_a_parked_question_may_be_asked_of_anyone_who_opens_that_part(self):
        held = work(questions={"q1": {**CAUSES, "status": "parked", "asked_of": None}})
        assert questions.may_ask(held, CAUSES, me=STEWARD["id"], on_screen="A3") == (None, "q1")

    def test_only_about_the_part_on_screen(self):
        assert questions.may_ask(work(), CAUSES, me=ADMIN["id"], on_screen="A4")[0].startswith("ask only about")

    def test_not_before_step_3(self):
        assert questions.may_ask(work(stage=2), CAUSES, me=ADMIN["id"], on_screen="A3")[0].startswith("questions start")


class TestAddFacts:
    def test_what_the_person_said_is_added_only_by_ask_user(self):
        assert "only through ask_user" in fact_rules.problem(work(), fact(origin="you_said"))

    def test_a_web_fact_needs_its_link_and_a_quote(self):
        assert "http link" in fact_rules.problem(work(), fact(origin="web", evidence="x" * 30))
        assert "quotes at least" in fact_rules.problem(work(), fact(origin="web", source_url="https://sesta.org"))

    @pytest.mark.parametrize(("value", "row"), [("₹2.4 crore", "income ₹2.40 crore [org:7]"),
                                                ("24765 families", "24,765 families reached [activity:41]")])
    def test_a_registry_value_is_found_however_its_digits_are_written(self, value, row):
        assert records.appears(value, [row])

    def test_a_registry_value_not_in_the_row_is_not_found(self):
        assert not records.appears("1,200", ["Staff: 120 [org:7]"])

    async def test_a_fact_is_checked_then_kept_once(self, monkeypatch):
        stored = {"work": work(stage=2)}
        p = context.Current(id=1, title="t", org_id=7, org_name="SeSTA", funder_id=3, funder_name="ABF",
                            work=stored["work"], scope=CallerScope(UUID(int=5), False, {7: "admin"}), can_edit=True)

        async def current():
            return p

        async def save(pool, proposal_id, change):
            applied = change(stored["work"], "t")
            stored["work"] = applied.work
            return applied

        async def lines(pool, p, marker):
            return ["Staff: 120 [org:7]"]

        async def user_name(pool, user_id):
            return ADMIN

        monkeypatch.setattr(context, "current", current)
        monkeypatch.setattr(ledger_tools, "get_pool", lambda: None)
        monkeypatch.setattr(records, "_lines", lines)
        monkeypatch.setattr(repo, "save", save)
        monkeypatch.setattr(repo, "user_name", user_name)
        staff = {"subject": "staff", "value": "120", "origin": "registry", "marker": "[org:7]", "section": "A10"}
        wrong = {**staff, "value": "1,200"}

        first = await ledger_tools.add_facts.ainvoke({"facts": [staff, wrong]})
        assert "k1 added: staff = 120 (green)" in first
        assert "REFUSED staff: '1,200' is not what [org:7] says" in first
        assert await ledger_tools.add_facts.ainvoke({"facts": [staff]}) == "k1 already held: staff = 120 (green)"
        assert list(stored["work"]["facts"]) == ["k1"]


PAGE = ("UDISE+ 2023-24. The dropout rate at the secondary level in Udalguri district was 19.8 per cent, "
        "against 15.1 per cent for Assam.")
URL = "https://udiseplus.gov.in/udalguri"


def public_fact(**kw):
    return {"subject": "secondary dropout rate, Udalguri", "value": "19.8%", "origin": "web", "section": "A3",
            "as_of": "2023-24", "source_url": URL, "source_name": "UDISE+ 2023-24",
            "evidence": "The dropout rate at the secondary level in Udalguri district was 19.8 per cent", **kw}


class TestPublicResearchQuotesThePage:
    def test_a_quote_on_the_page_it_read_is_kept(self):
        assert fact_rules.off_page(public_fact(), PAGE) is None

    def test_a_quote_not_on_the_page_is_refused(self):
        made_up = public_fact(evidence="Udalguri has the highest dropout rate in Assam, at 19.8 per cent")
        assert "not on" in fact_rules.off_page(made_up, PAGE)

    def test_a_page_it_did_not_read_is_refused(self):
        assert "was not read in this run" in fact_rules.off_page(public_fact(), None)

    def test_a_fact_without_its_year_is_refused(self):
        assert "year" in fact_rules.off_page(public_fact(as_of=""), PAGE)

    @pytest.mark.parametrize("as_of", ["undated", "recent"])
    def test_a_year_must_be_in_digits(self, as_of):
        assert "year" in fact_rules.off_page(public_fact(as_of=as_of), PAGE)

    def test_a_period_with_a_year_is_kept(self):
        assert fact_rules.off_page(public_fact(as_of="2019-21"), PAGE) is None

    def test_wikipedia_is_not_a_source(self):
        cited = public_fact(source_url="https://en.wikipedia.org/wiki/Udalguri_district")
        assert "Wikipedia" in fact_rules.off_page(cited, PAGE)

    def test_a_number_the_quote_does_not_hold_is_refused(self):
        assert "every number" in fact_rules.off_page(public_fact(value="21.8%"), PAGE)

    def test_only_the_sections_public_evidence_serves(self):
        assert "fills" in fact_rules.off_page(public_fact(section="A10"), PAGE)

    async def test_add_facts_in_a_public_run_marks_what_it_keeps(self, monkeypatch):
        from app.proposals.middleware import PUBLIC_RUN, PublicRun, page_key

        stored = {"work": work(stage=2)}
        p = context.Current(id=1, title="t", org_id=7, org_name="SeSTA", funder_id=3, funder_name="ABF",
                            work=stored["work"], scope=CallerScope(UUID(int=5), False, {7: "admin"}), can_edit=True)

        async def current():
            return p

        async def save(pool, proposal_id, change):
            applied = change(stored["work"], "t")
            stored["work"] = applied.work
            return applied

        async def user_name(pool, user_id):
            return ADMIN

        monkeypatch.setattr(context, "current", current)
        monkeypatch.setattr(ledger_tools, "get_pool", lambda: None)
        monkeypatch.setattr(repo, "save", save)
        monkeypatch.setattr(repo, "user_name", user_name)
        token = PUBLIC_RUN.set(PublicRun(avoid=("SeSTA",), pages={page_key(URL): PAGE}))
        try:
            out = await ledger_tools.add_facts.ainvoke({"facts": [public_fact(), public_fact(value="21.8%")]})
        finally:
            PUBLIC_RUN.reset(token)
        assert "k1 added" in out and "REFUSED" in out
        assert stored["work"]["facts"]["k1"]["found_by"] == "public"

    def test_outside_public_research_a_web_fact_keeps_todays_rule(self):
        assert fact_rules.problem(work(), public_fact(evidence="a sentence quoted from the brief")) is None
        assert "found_by" not in fact_rules.make(public_fact())


class TestOnlySangamPitchAddsFacts:
    def test_a_screen_save_cannot_add_a_fact(self):
        with pytest.raises(rules.BadChange):
            rules.apply(work(), {"facts.k1": fact()}, by=ADMIN)

    def test_a_correction_keeps_the_old_fact_and_adds_the_persons(self):
        applied = rules.apply(work(facts={"k1": fact()}), {"facts.k1.correct": "104"}, by=ADMIN)
        assert applied.work["facts"]["k1"]["status"] == "corrected"
        assert applied.work["facts"]["k2"].items() >= {"value": "104", "origin": "you_said", "supersedes": "k1",
                                                        "status": "confirmed", "said_by": ADMIN}.items()

"""The post-answer audit: what it looks at, and that it never breaks a turn."""

from __future__ import annotations

from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.ask import audit as audit_mod
from app.ask.audit import Audit, audit_turn, collect_turn, executed_sql

MODEL = "anthropic:claude-haiku-5-5"


def turn(answer="KABIL has the highest score, 93.", *, with_sql=True):
    messages = [HumanMessage("Which org has the highest fit score?")]
    if with_sql:
        messages.append(
            ToolMessage(
                content='1 row(s).\nexecuted: SELECT "o"."name" FROM "orgs" AS "o" LIMIT 51\n'
                "columns: name\nKABIL",
                name="db_query",
                tool_call_id="1",
            )
        )
    messages.append(AIMessage(content=answer))
    return messages


def query(content, sql="SELECT 1", call_id="1"):
    return ToolMessage(content, name="db_query", tool_call_id=call_id, artifact={"sql": sql})


class FakeModel:
    """Stands in for the judge: `reply` is the JSON the structured output would carry, or None for no verdict."""

    def __init__(self, reply, stop_reason="end_turn"):
        self.reply, self.stop_reason = reply, stop_reason
        self.calls, self.prompt, self.max_tokens, self.schema = 0, "", None, None

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return self

    def invoke(self, prompt, **kwargs):
        self.calls += 1
        self.prompt = prompt
        raw = AIMessage(content="", response_metadata={"stop_reason": self.stop_reason})
        try:
            parsed = self.schema.model_validate_json(self.reply) if self.reply else None
        except ValueError:
            parsed = None
        return {"raw": raw, "parsed": parsed, "parsing_error": None}


@pytest.fixture
def fake_model(monkeypatch):
    def install(reply):
        model = FakeModel(reply)
        monkeypatch.setattr(audit_mod, "resolve_model", lambda spec: model)
        return model
    return install


class TestWhatItReads:
    def test_collects_question_sql_and_answer(self):
        collected = collect_turn(turn())
        assert collected.question.startswith("Which org")
        [block] = collected.evidence
        assert 'SQL: SELECT "o"."name" FROM "orgs" AS "o" LIMIT 51' in block
        assert "KABIL" in block
        assert collected.answer == "KABIL has the highest score, 93."

    def test_a_new_user_message_starts_a_turn_and_keeps_earlier_results_as_earlier(self):
        """The previous turn's rows stay as evidence, marked, but this turn ran no query, so it is not audited."""
        messages = turn() + [HumanMessage("And the lowest?"), AIMessage("BDF, 41.")]
        collected = collect_turn(messages)
        assert collected.question == "And the lowest?"
        [block] = collected.evidence
        assert block.startswith('(earlier question: "Which org has the highest fit score?")')
        assert not collected.has_data
        assert collected.answer == "BDF, 41."

    def test_every_query_in_the_turn_is_kept(self):
        """Ask runs 3-5 queries a turn; keeping only the last flagged facts that came from the others."""
        messages = [
            HumanMessage("What does PRDA do?"),
            query("1 row(s).\ncolumns: name\nPRDA", "SELECT name FROM orgs", "1"),
            query("4 row(s).\ncolumns: district\nBishnupur\nChandel\nNoney\nThoubal", "SELECT district", "2"),
            query("2 row(s).\ncolumns: funder\nTata Trusts\nAxis", "SELECT funder", "3"),
            AIMessage("PRDA works in four districts."),
        ]
        evidence = collect_turn(messages).evidence
        assert len(evidence) == 3
        assert "Thoubal" in evidence[1] and "SQL: SELECT district" in evidence[1]

    def test_compare_fit_output_is_evidence(self):
        messages = [
            HumanMessage("How well does KABIL fit Axis?"),
            ToolMessage("1 funder checked.\nAxis Bank Foundation · 82 strong", name="compare_fit", tool_call_id="1"),
            AIMessage("Axis is a strong fit, 82 [score:4]."),
        ]
        [block] = collect_turn(messages).evidence
        assert block.startswith("compare_fit") and "82 strong" in block

    @pytest.mark.parametrize("content, name", [
        ("db_query rejected: unknown column", "db_query"),
        ("db_query failed: the database is unreachable right now.", "db_query"),
        ("compare_fit refused: running a match for organisation 7 is for its stewards.", "compare_fit"),
        ("compare_fit failed: no organisation with id 7", "compare_fit"),
        ("orgs: id, name", "db_describe_table"),
    ])
    def test_failures_refusals_and_schema_reads_are_not_data(self, content, name):
        assert not collect_turn([HumanMessage("q"), ToolMessage(content, name=name, tool_call_id="1")]).has_data

    def test_a_failure_is_shown_beside_the_results(self):
        """An answer that says 'its funding could not be retrieved' is right, not unsupported."""
        messages = [HumanMessage("q"), query("1 row(s).\nPRDA", "SELECT 1", "1"),
                    query("db_query failed: statement timeout", "SELECT 2", "2"), AIMessage("a")]
        collected = collect_turn(messages)
        assert collected.has_data
        assert collected.evidence[1].startswith("db_query (no data)\nSQL: SELECT 2") and "statement timeout" in collected.evidence[1]

    def test_a_long_result_is_cut_and_says_so(self):
        """Unmarked, a funder from row 40 of 51 looked unsupported."""
        [block] = collect_turn([HumanMessage("q"), query("x" * (audit_mod.RESULT_CHARS + 500))]).evidence
        assert block.count("x") == audit_mod.RESULT_CHARS
        assert block.endswith("(cut: 500 more characters not shown)")

    def test_a_profile_and_graph_facts_are_evidence(self):
        """'42 organisations are in Assam' can come from a profile count, not a query."""
        messages = [
            HumanMessage("q"),
            ToolMessage("org_locations.state: ASSAM 42", name="db_profile_column", tool_call_id="1"),
            ToolMessage("[graph:ab12cd34] KABIL co-implements with Axis", name="search_graph", tool_call_id="2"),
        ]
        collected = collect_turn(messages)
        assert collected.has_data
        assert [b.splitlines()[0] for b in collected.evidence] == ["db_profile_column", "search_graph"]

    @pytest.mark.parametrize("content", [
        "The knowledge graph is not available (no NEO4J_URI). Answer from the database tools instead.",
        "No graph facts found for 'KABIL'.",
        "search_graph failed: timeout",
    ])
    def test_an_empty_graph_is_not_data(self, content):
        collected = collect_turn([HumanMessage("q"), ToolMessage(content, name="search_graph", tool_call_id="1")])
        assert not collected.has_data and collected.evidence[0].startswith("search_graph (no data)")

    def test_a_failed_page_back_is_not_data(self):
        messages = [
            HumanMessage("q"),
            AIMessage("", tool_calls=[{"id": "r1", "name": "read_file", "args": {"file_path": "/large_tool_results/x"}}]),
            ToolMessage("read_file failed: FileNotFoundError. Try another way.", name="read_file", tool_call_id="r1"),
        ]
        assert not collect_turn(messages).has_data

    def test_a_shortlist_keeps_more_than_a_query(self):
        shortlist = "z" * (audit_mod.RESULT_CHARS * 3)
        [block] = collect_turn([HumanMessage("q"), ToolMessage(shortlist, name="compare_fit", tool_call_id="1")]).evidence
        assert block.count("z") == audit_mod.RESULT_CHARS * 3

    def test_a_result_paged_back_from_a_file_is_evidence(self):
        """A big result is moved to a file and read back; the stub alone would leave every figure unsupported."""
        messages = [
            HumanMessage("q"),
            AIMessage("", tool_calls=[
                {"id": "r1", "name": "read_file", "args": {"file_path": "/large_tool_results/call_1"}},
                {"id": "r2", "name": "read_file", "args": {"file_path": "/skills/news-brief/SKILL.md"}},
            ]),
            ToolMessage("Thoubal 12", name="read_file", tool_call_id="r1"),
            ToolMessage("# News brief", name="read_file", tool_call_id="r2"),
            AIMessage("Thoubal has 12."),
        ]
        collected = collect_turn(messages)
        assert collected.has_data
        assert [b.splitlines()[0] for b in collected.evidence] == ["read_file (a large result paged back)"]


class TestTheSqlThatRan:
    def test_it_comes_from_the_artifact(self):
        message = ToolMessage("1 row(s).", name="db_query", tool_call_id="1", artifact={"sql": "SELECT 2"})
        assert executed_sql(message) == ["SELECT 2"]

    def test_a_failure_or_an_older_result_carries_it_in_the_text(self):
        assert executed_sql(ToolMessage("executed: SELECT 1", name="db_query", tool_call_id="1")) == ["SELECT 1"]
        assert executed_sql(ToolMessage("db_query rejected: x", name="db_query", tool_call_id="1")) == []


class TestWhenItRuns:
    def test_disabled_when_no_model_is_configured(self, fake_model):
        model = fake_model('{"verdict":"warn","caveat":"x"}')
        assert audit_turn(turn(), "") is None
        assert model.calls == 0, "must not spend a call when disabled"

    def test_skipped_when_no_data_came_back(self, fake_model):
        """A turn with no db_query or compare_fit result has nothing to audit and must be free."""
        model = fake_model('{"verdict":"warn","caveat":"x"}')
        assert audit_turn(turn(with_sql=False), MODEL) is None
        assert model.calls == 0

    def test_a_refusal_turn_is_not_audited(self, fake_model):
        """Nothing came back to check the answer against, so the audit could only invent a problem."""
        model = fake_model('{"verdict":"warn","caveat":"x"}')
        messages = [
            HumanMessage("Match KABIL against every funder"),
            query("1 row(s).\ncolumns: id, name\n7 KABIL", "SELECT id FROM orgs", "0"),
            ToolMessage("compare_fit refused: running a match for organisation 7 is for its stewards.",
                        name="compare_fit", tool_call_id="1"),
            AIMessage("Running a match for KABIL is for its stewards, admins and Sangam staff."),
        ]
        assert audit_turn(messages, MODEL) is None
        assert model.calls == 0

    def test_a_budget_refusal_after_a_match_is_still_audited(self, fake_model):
        """CompareFitBudget refusing a repeat is not the caller being refused: the first match stands."""
        model = fake_model('{"verdict":"ok"}')
        messages = [
            HumanMessage("q"),
            ToolMessage("Axis Bank Foundation · 82 strong", name="compare_fit", tool_call_id="1"),
            ToolMessage("compare_fit refused a repeat: it already ran with these arguments this turn.",
                        name="compare_fit", tool_call_id="2"),
            AIMessage("Axis is a strong fit, 82."),
        ]
        assert audit_turn(messages, MODEL) == Audit("ok")
        assert model.calls == 1

    async def test_the_refusal_prefix_is_what_compare_fit_returns(self, monkeypatch):
        from app.ask.tools import matching_tools

        async def no(*args): return False
        monkeypatch.setattr(matching_tools.matching, "may_run", no)
        monkeypatch.setattr(matching_tools, "get_pool", lambda: None)
        reply = await matching_tools.compare_fit.ainvoke({"org_id": 7})
        assert reply.startswith(audit_mod.COMPARE_FIT_REFUSED)

    def test_the_newest_results_survive_the_cap(self, fake_model, monkeypatch):
        model = fake_model('{"verdict":"ok"}')
        monkeypatch.setattr(audit_mod, "EVIDENCE_CHARS", 200)
        messages = [HumanMessage("q"), query("old " * 100, "SELECT 1", "1"), query("newest rows", "SELECT 2", "2"),
                    AIMessage("answer")]
        audit_turn(messages, MODEL)
        assert "newest rows" in model.prompt and "SQL: SELECT 1" not in model.prompt
        assert "(1 earlier results not shown)\n\ndb_query\nSQL: SELECT 2" in model.prompt, "whole blocks, header kept"

    def test_a_turn_whose_queries_all_failed_is_not_audited(self, fake_model):
        model = fake_model('{"verdict":"warn","caveat":"x"}')
        messages = [HumanMessage("q"), query("db_query failed: the database is unreachable right now."),
                    AIMessage("The data could not be reached.")]
        assert audit_turn(messages, MODEL) is None
        assert model.calls == 0

    def test_a_compare_fit_turn_is_audited_without_sql(self, fake_model):
        model = fake_model('{"verdict":"ok"}')
        messages = [
            HumanMessage("How well does KABIL fit Axis?"),
            ToolMessage("Axis Bank Foundation · 82 strong", name="compare_fit", tool_call_id="1"),
            AIMessage("Axis is a strong fit, 82."),
        ]
        assert audit_turn(messages, MODEL) == Audit("ok")
        assert "82 strong" in model.prompt

    def test_the_prompt_carries_every_result_and_today(self, fake_model):
        """Without today's date the audit called a fetch date twelve days old 'in the future'."""
        model = fake_model('{"verdict":"ok"}')
        messages = [HumanMessage("q"), query("1 row(s).\nalpha", "SELECT 1", "1"),
                    query("1 row(s).\nbeta", "SELECT 2", "2"), AIMessage("the answer")]
        before = datetime.now(audit_mod.IST).date().isoformat()
        audit_turn(messages, MODEL)
        after = datetime.now(audit_mod.IST).date().isoformat()
        assert "SQL: SELECT 1" in model.prompt and "alpha" in model.prompt and "beta" in model.prompt
        assert f"Today is {before}." in model.prompt or f"Today is {after}." in model.prompt

    def test_skipped_when_there_is_no_answer_yet(self, fake_model):
        model = fake_model('{"verdict":"ok"}')
        messages = [HumanMessage("q"), ToolMessage(content="executed: SELECT 1", name="db_query", tool_call_id="1")]
        assert audit_turn(messages, MODEL) is None
        assert model.calls == 0


class TestVerdicts:
    def test_ok(self, fake_model):
        fake_model('{"verdict": "ok"}')
        assert audit_turn(turn(), MODEL) == Audit("ok")

    def test_warn_carries_the_caveat(self, fake_model):
        fake_model('{"verdict":"warn","check":"filters","reason":"The question said Assam but the SQL has no state filter."}')
        result = audit_turn(turn(), MODEL)
        assert result.verdict == "warn"
        assert "no state filter" in result.caveat

    def test_warn_names_the_check_that_failed(self, fake_model):
        fake_model('{"verdict":"warn","check":"grain","reason":"counts grants, not orgs"}')
        assert audit_turn(turn(), MODEL) == Audit("warn", "counts grants, not orgs", "grain")

    def test_the_judge_gets_room_and_a_fixed_shape(self, fake_model):
        """1024 tokens ran out while thinking and no verdict came (#452)."""
        model = fake_model('{"verdict":"ok"}')
        audit_turn(turn(), MODEL)
        assert model.max_tokens == audit_mod.MAX_TOKENS >= 4096
        assert model.schema is audit_mod.Verdict

    def test_thinking_that_uses_up_the_cap_is_logged(self, fake_model, monkeypatch, caplog):
        monkeypatch.setattr(audit_mod, "resolve_model", lambda spec: FakeModel(None, stop_reason="max_tokens"))
        assert audit_turn(turn(), MODEL) is None
        assert "max_tokens" in caplog.text

    def test_warn_without_a_caveat_is_still_a_warning(self, fake_model):
        fake_model('{"verdict":"warn"}')
        assert audit_turn(turn(), MODEL) == Audit("warn")


class TestFailsOpen:
    """A second opinion must never break a turn."""

    def test_model_raises(self, monkeypatch):
        class Boom:
            def invoke(self, *a, **k): raise RuntimeError("provider down")
        monkeypatch.setattr(audit_mod, "resolve_model", lambda spec: Boom())
        assert audit_turn(turn(), MODEL) is None

    def test_unresolvable_model(self, monkeypatch):
        monkeypatch.setattr(
            audit_mod, "resolve_model",
            lambda spec: (_ for _ in ()).throw(ValueError("no such provider")),
        )
        assert audit_turn(turn(), MODEL) is None

    def test_unparseable_reply(self, fake_model):
        fake_model("I could not determine that.")
        assert audit_turn(turn(), MODEL) is None

    def test_a_verdict_outside_the_schema(self, fake_model):
        fake_model('{"verdict": "maybe"}')
        assert audit_turn(turn(), MODEL) is None


def test_an_appended_caveat_is_not_mistaken_for_the_answer():
    """The caveat is a second AIMessage. Anything reading 'the last AI message' would audit the caveat
    instead of the answer — and the eval harness would"""
    from app.ask.audit import CAVEAT_PREFIX

    messages = turn() + [AIMessage(content=f"{CAVEAT_PREFIX} the SQL has no state filter")]
    assert collect_turn(messages).answer == "KABIL has the highest score, 93."


class TestTheWholeChat:
    """An answer may reuse what an earlier question found; the audit used to call that unsupported (#451)."""

    def chat(self):
        return [
            HumanMessage("what does axis bank foundation do?"),
            query("1 row(s).\n[activity:1] Sustainable livelihoods project, Udalguri", "SELECT * FROM funder_activity", "1"),
            AIMessage("It funded KABIL's Udalguri project [activity:1]."),
            HumanMessage("who works in udalguri?"),
            query("2 row(s).\n[org:1] KABIL\n[org:4] Rural Volunteers", "SELECT * FROM org_locations", "2"),
            AIMessage("KABIL [org:1], with Axis's past project [activity:1], and Rural Volunteers [org:4]."),
        ]

    def test_earlier_results_are_evidence_marked_with_their_question(self):
        collected = collect_turn(self.chat())
        assert collected.question == "who works in udalguri?"
        earlier, current = collected.evidence
        assert earlier.startswith('(earlier question: "what does axis bank foundation do?")\n')
        assert "[activity:1]" in earlier
        assert not current.startswith("(earlier") and "Rural Volunteers" in current
        assert collected.answer.startswith("KABIL [org:1]")

    def test_a_result_is_marked_once_with_the_question_that_found_it(self):
        messages = self.chat() + [HumanMessage("and in assam?"), query("0 row(s).", "SELECT 3", "3"), AIMessage("None.")]
        first, second, _ = collect_turn(messages).evidence
        assert first.count("(earlier question") == 1 and second.startswith('(earlier question: "who works in udalguri?")')

    def test_only_this_turns_data_decides_whether_to_audit(self, fake_model):
        """A follow-up that ran no query is talk, not a data answer: earlier rows alone don't make it auditable."""
        model = fake_model('{"verdict":"ok"}')
        messages = self.chat() + [HumanMessage("thanks"), AIMessage("You're welcome.")]
        assert audit_turn(messages, MODEL) is None and model.calls == 0

    def test_the_prompt_carries_the_earlier_result(self, fake_model):
        model = fake_model('{"verdict":"ok"}')
        assert audit_turn(self.chat(), MODEL) == Audit("ok")
        assert '(earlier question: "what does axis bank foundation do?")' in model.prompt
        assert "Sustainable livelihoods project, Udalguri" in model.prompt
        assert "the answer may reuse it" in model.prompt

    def test_a_long_chat_keeps_the_rows_the_answer_cites_from_dropped_results(self, fake_model, monkeypatch):
        """19 Nov, question 10: the cap had dropped question 3's [activity:1], so a correct answer was flagged."""
        model = fake_model('{"verdict":"ok"}')
        monkeypatch.setattr(audit_mod, "EVIDENCE_CHARS", 300)
        messages = self.chat()[:3] + [
            HumanMessage("top 5 funders in livelihoods"),
            query("5 row(s).\n" + "[funder:9] Some Funder, livelihoods\n" * 8, "SELECT * FROM funders", "3"),
            AIMessage("Axis has a past Udalguri project [activity:1]; Some Funder [funder:9] leads."),
        ]
        audit_turn(messages, MODEL)
        assert "[activity:1] Sustainable livelihoods project, Udalguri" in model.prompt
        assert "(only the rows the answer cites)" in model.prompt
        assert "SQL: SELECT * FROM funder_activity" in model.prompt, "the header says where the row came from"
        assert "(1 earlier results not shown)" in model.prompt

    def test_a_dropped_result_the_answer_does_not_cite_stays_out(self, fake_model, monkeypatch):
        model = fake_model('{"verdict":"ok"}')
        monkeypatch.setattr(audit_mod, "EVIDENCE_CHARS", 300)
        messages = self.chat()[:3] + [
            HumanMessage("top 5"), query("5 row(s).\n" + "[funder:9] Some Funder\n" * 8, "SELECT 9", "3"),
            AIMessage("Some Funder [funder:9] leads."),
        ]
        audit_turn(messages, MODEL)
        assert "Sustainable livelihoods" not in model.prompt

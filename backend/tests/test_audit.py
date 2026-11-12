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
    def __init__(self, reply): self.reply = reply; self.calls = 0; self.prompt = ""
    def invoke(self, prompt, **kwargs):
        self.calls += 1
        self.prompt = prompt
        return AIMessage(content=self.reply)


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

    def test_a_new_user_message_resets_the_turn(self):
        """Auditing the previous turn's SQL against this turn's answer would
        manufacture caveats out of nothing."""
        messages = turn() + [HumanMessage("And the lowest?"), AIMessage("BDF, 41.")]
        collected = collect_turn(messages)
        assert collected.question == "And the lowest?"
        assert collected.evidence == []
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
        assert collected.evidence[1].startswith("db_query (no rows)") and "statement timeout" in collected.evidence[1]

    def test_a_long_result_is_cut(self):
        [block] = collect_turn([HumanMessage("q"), query("x" * (audit_mod.RESULT_CHARS + 500))]).evidence
        assert block.count("x") == audit_mod.RESULT_CHARS

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
        fake_model('{"verdict":"warn","caveat":"The question said Assam but the SQL has no state filter."}')
        result = audit_turn(turn(), MODEL)
        assert result.verdict == "warn"
        assert "no state filter" in result.caveat

    def test_json_wrapped_in_prose_is_still_read(self, fake_model):
        """Small models preface JSON with chatter however firmly you ask."""
        fake_model('Here is my assessment:\n{"verdict":"warn","caveat":"grain mismatch"}\nHope that helps.')
        assert audit_turn(turn(), MODEL).caveat == "grain mismatch"

    def test_a_reply_that_starts_with_thinking_is_still_read(self, fake_model):
        """Haiku 5.5 thinks by default, so content is a list with a thinking block first."""
        fake_model([{"type": "thinking", "thinking": "", "signature": "s"},
                    {"type": "text", "text": '{"verdict":"warn","caveat":"grain mismatch"}'}])
        assert audit_turn(turn(), MODEL).caveat == "grain mismatch"

    def test_thinking_that_uses_up_the_cap_is_logged(self, fake_model, monkeypatch, caplog):
        model = fake_model([{"type": "thinking", "thinking": "", "signature": "s"}])
        monkeypatch.setattr(model, "invoke", lambda prompt, **kw: AIMessage(
            content=model.reply, response_metadata={"stop_reason": "max_tokens"}))
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

    def test_malformed_json(self, fake_model):
        fake_model('{"verdict": "warn", caveat: unquoted}')
        assert audit_turn(turn(), MODEL) is None


def test_an_appended_caveat_is_not_mistaken_for_the_answer():
    """The caveat is a second AIMessage. Anything reading 'the last AI message' would audit the caveat
    instead of the answer — and the eval harness would"""
    from app.ask.audit import CAVEAT_PREFIX

    messages = turn() + [AIMessage(content=f"{CAVEAT_PREFIX} the SQL has no state filter")]
    assert collect_turn(messages).answer == "KABIL has the highest score, 93."

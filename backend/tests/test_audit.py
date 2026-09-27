"""The post-answer audit: what it looks at, and that it never breaks a turn.

No API calls — resolve_model is monkeypatched, so every path including the
failure paths is exercised for free.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import audit as audit_mod
from app.agent.audit import Audit, audit_turn, collect_turn

MODEL = "anthropic:claude-haiku-4-5"


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


class FakeModel:
    def __init__(self, reply): self.reply = reply; self.calls = 0
    def invoke(self, prompt, **kwargs):
        self.calls += 1
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
        question, sql, result, answer = collect_turn(turn())
        assert question.startswith("Which org")
        assert sql == ['SELECT "o"."name" FROM "orgs" AS "o" LIMIT 51']
        assert "KABIL" in result
        assert answer == "KABIL has the highest score, 93."

    def test_a_new_user_message_resets_the_turn(self):
        """Auditing the previous turn's SQL against this turn's answer would
        manufacture caveats out of nothing."""
        messages = turn() + [HumanMessage("And the lowest?"), AIMessage("BDF, 41.")]
        question, sql, _, answer = collect_turn(messages)
        assert question == "And the lowest?"
        assert sql == []
        assert answer == "BDF, 41."


class TestWhenItRuns:
    def test_disabled_when_no_model_is_configured(self, fake_model):
        model = fake_model('{"verdict":"warn","caveat":"x"}')
        assert audit_turn(turn(), "") is None
        assert model.calls == 0, "must not spend a call when disabled"

    def test_skipped_when_no_sql_ran(self, fake_model):
        """Curated-tool turns have nothing SQL-shaped to audit and must be free."""
        model = fake_model('{"verdict":"warn","caveat":"x"}')
        assert audit_turn(turn(with_sql=False), MODEL) is None
        assert model.calls == 0

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

    def test_warn_without_a_caveat_is_not_actionable(self, fake_model):
        fake_model('{"verdict":"warn"}')
        assert audit_turn(turn(), MODEL) == Audit("ok")


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

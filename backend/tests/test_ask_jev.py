"""Jev in Ask: its questions, the labels a turn gives them, and the shadow scores."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.ask import jev
from app.ask.agent import SKILLS_DIR
from app.core.config import Settings
from app.integrations.typesafe import Decision


def _read_skill(name, call_id="s1"):
    return AIMessage(content="", tool_calls=[
        {"name": "read_file", "args": {"file_path": f"/skills/{name}/SKILL.md"}, "id": call_id}])


def _decision(route="catalog", skill="funder-comparison"):
    return Decision(
        answers={
            "route": {"type": "choice", "choice": route, "confidence": 0.9, "probabilities": {route: 0.9}},
            "skill": {"type": "choice", "choice": skill, "confidence": 0.8, "probabilities": {skill: 0.8}},
        },
        model="jev-latest", input_tokens=100, estimated=False, latency_ms=120, cost_usd=0.0,
    )


KABIL = [
    HumanMessage("How well does KABIL fit Axis Bank Foundation?"),
    _read_skill("funder-comparison"),
    ToolMessage("skill text", tool_call_id="s1", name="read_file"),
    AIMessage(content="", tool_calls=[{"name": "compare_fit", "args": {"org_id": 1}, "id": "c1"}]),
    ToolMessage("[funder:3] score 71", tool_call_id="c1", name="compare_fit"),
    AIMessage("KABIL is a medium fit [funder:3]."),
]
WEATHER = [HumanMessage("what is the weather today?"), AIMessage("I can't tell you the weather.")]


def test_every_ask_skill_is_a_choice_with_its_description():
    skills = jev.skill_catalog(SKILLS_DIR)
    assert set(skills) == {"funder-comparison", "funder-matching", "funder-shortlist-brief", "news-brief"}
    assert all(desc.startswith("Use when") for desc in skills.values())
    criteria = jev.questions(skills)["skill"]["criteria"]
    assert set(criteria) == set(skills) | {jev.NO_SKILL}


def test_a_skill_without_frontmatter_is_named_by_its_folder(tmp_path):
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "SKILL.md").write_text("no frontmatter here")
    assert jev.skill_catalog(tmp_path) == {"plain": ""}


def test_the_state_is_the_question_and_the_one_before():
    chat = [HumanMessage("Which funders fit KABIL?"), AIMessage("Five."), HumanMessage("and Goonj?")]
    assert jev.asked(chat) == {"question": "and Goonj?", "previous_question": "Which funders fit KABIL?"}
    assert jev.asked(WEATHER) == {"question": "what is the weather today?", "previous_question": None}
    assert jev.asked([AIMessage("hi")]) is None


def test_a_long_question_is_cut():
    assert len(jev.asked([HumanMessage("x" * 5000)])["question"]) == jev.QUESTION_CHARS


def test_the_label_is_this_turns_skills_and_data():
    assert jev.did(KABIL) == jev.Did(("funder-comparison",), True)
    assert jev.did(WEATHER) == jev.Did((), False)
    # An earlier turn's skill read is not this turn's.
    assert jev.did([*KABIL, HumanMessage("thanks"), AIMessage("You're welcome.")]) == jev.Did((), False)


def test_two_reads_of_the_same_skill_count_once():
    turn = [HumanMessage("q"), _read_skill("funder-matching", "a"), _read_skill("funder-matching", "b"),
            _read_skill("funder-shortlist-brief", "c")]
    assert jev.did(turn).skills == ("funder-matching", "funder-shortlist-brief")


@pytest.fixture
def scores(monkeypatch):
    seen = []
    monkeypatch.setattr(jev, "score_answer", lambda name, value, comment=None, metadata=None: seen.append((name, value)))
    return seen


@pytest.mark.parametrize("route, label, agree", [
    ("catalog", jev.Did((), True), 1.0),
    ("off_topic", jev.Did((), False), 1.0),
    ("research", jev.Did((), False), 1.0),
    ("off_topic", jev.Did((), True), 0.0),
    ("catalog", jev.Did((), False), 0.0),
])
def test_route_agreement(scores, route, label, agree):
    jev.score_route(_decision(route=route), label)
    assert scores == [("jev_route_agree", agree)]


@pytest.mark.parametrize("skill, label, agree", [
    ("funder-comparison", jev.Did(("funder-comparison",), True), 1.0),
    ("none", jev.Did((), True), 1.0),
    ("funder-matching", jev.Did(("funder-matching", "funder-shortlist-brief"), True), 1.0),
    ("funder-shortlist-brief", jev.Did(("funder-matching", "funder-shortlist-brief"), True), 0.0),
    ("news-brief", jev.Did((), True), 0.0),
])
def test_skill_agreement_is_with_the_first_skill_read(scores, skill, label, agree):
    jev.score_skill(_decision(skill=skill), label)
    assert scores == [("jev_skill_agree", agree)]


def test_an_unanswered_question_scores_nothing(scores):
    empty = Decision({}, "jev-latest", 0, True, 0, 0.0)
    jev.score_route(empty, jev.Did((), True))
    jev.score_skill(empty, jev.Did((), True))
    assert scores == []


def _shadow(monkeypatch, route="shadow", skill="shadow", decision=None):
    sent = []

    def fake_decide(state, questions, *, name, settings):
        sent.append((state, set(questions), name))
        return decision

    monkeypatch.setattr(jev, "decide", fake_decide)
    settings = Settings(_env_file=None, typesafe_api_key="k", jev_route=route, jev_skill=skill)
    return jev.jev_shadow(settings, jev.skill_catalog(SKILLS_DIR)), sent


def test_shadow_asks_after_the_answer_and_scores_both(monkeypatch, scores):
    hook, sent = _shadow(monkeypatch, decision=_decision())
    assert hook.after_agent({"messages": KABIL}, None) is None
    assert sent == [({"question": KABIL[0].text, "previous_question": None}, {"route", "skill"}, "jev_route_skill")]
    assert scores == [("jev_route_agree", 1.0), ("jev_skill_agree", 1.0)]


def test_shadow_asks_only_the_questions_switched_on(monkeypatch, scores):
    hook, sent = _shadow(monkeypatch, route="off", decision=None)
    hook.after_agent({"messages": KABIL}, None)
    assert sent[0][1] == {"skill"}


def test_shadow_with_no_question_or_no_answer_scores_nothing(monkeypatch, scores):
    hook, sent = _shadow(monkeypatch, decision=None)
    hook.after_agent({"messages": [AIMessage("hi")]}, None)
    assert sent == []
    hook.after_agent({"messages": KABIL}, None)
    assert len(sent) == 1 and scores == []


@pytest.mark.parametrize("keys, wired", [
    ({}, False),
    ({"typesafe_api_key": "k", "jev_skill": "shadow"}, False),  # no Langfuse: the score has nowhere to land
    ({"typesafe_api_key": "k", "langfuse_public_key": "pk", "langfuse_secret_key": "sk"}, False),  # all off
    ({"typesafe_api_key": "k", "jev_skill": "shadow", "langfuse_public_key": "pk", "langfuse_secret_key": "sk"}, True),
])
def test_shadow_is_wired_only_with_a_key_langfuse_and_a_mode(keys, wired):
    from langgraph.checkpoint.memory import InMemorySaver

    from app.ask.agent import build_agent

    graph = build_agent(Settings(_env_file=None, **keys), InMemorySaver())
    assert ("jev_shadow.after_agent" in graph.nodes) is wired

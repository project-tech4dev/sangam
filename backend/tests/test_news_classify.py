"""The classifiers: what the model is asked, and a malformed reply raising rather than inventing a verdict."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.ingest.adapters.tavily_news import Hit
from app.ingest.news import classify
from app.ingest.news.feeds import Subject

HIT = Hit(url="https://eastmojo.com/a", title="KABIL trains weavers", snippet="s", text="Udalguri women...",
          published=None, query='"KABIL"', scope="open_web")
KABIL = Subject(kind="org", id=9, key="kabil", name="KABIL", place="Udalguri")


class FakeModel:
    """Stands in for a LangChain chat model: records the prompt, returns a canned structured reply."""

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.prompts.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.schema.model_validate(self.reply)


VERDICT = {"on_target": True, "match": 0.9, "confidence": 0.92, "content_kind": "news", "is_news": True,
           "event_date": "2026-10-02", "stance": "positive", "signal_type": "programme_result",
           "region": {"state": "Assam", "district": "Udalguri"}, "sector_tags": ["livelihoods"],
           "summary": "KABIL trained 200 women weavers."}


async def test_the_entity_prompt_carries_the_profile_and_the_item():
    model = FakeModel(VERDICT)
    v = await classify.classify_entity(model, KABIL, HIT)
    system, user = model.prompts[0]
    assert "Khanij Bidesh" in user[1] and "KABIL trains weavers" in user[1] and "Namesakes" in system[1]
    assert v.match == 0.9 and v.event_date == date(2026, 10, 2) and v.region.district == "Udalguri"


async def test_a_malformed_reply_raises():
    with pytest.raises(ValidationError):
        await classify.classify_entity(FakeModel({"on_target": "maybe"}), KABIL, HIT)


async def test_the_topic_prompt_lists_the_registry_names():
    reply = {"on_target": True, "match": 0.8, "confidence": 0.9, "topic": "fcra", "content_kind": "news",
             "is_news": True, "event_date": None, "scope": "north_east", "region": {"state": "Nagaland",
             "district": None}, "sentiment": "negative", "registry_named": ["Better Life Foundation"],
             "sector_tags": [], "summary": "FCRA rules tightened."}
    model = FakeModel(reply)
    v = await classify.classify_topic(model, "fcra", HIT, ["Better Life Foundation", "KABIL"])
    assert "Better Life Foundation, KABIL" in model.prompts[0][0][1]
    assert v.registry_named == ["Better Life Foundation"]


def test_values_outside_the_lists_become_other_rather_than_losing_the_item():
    v = classify.EntityVerdict.model_validate(VERDICT | {
        "content_kind": "open_call", "signal_type": "fundraiser", "event_date": "2025",
        "sector_tags": ["livelihoods", "infrastructure"], "stance": "mixed"})
    assert (v.content_kind, v.signal_type, v.event_date, v.sector_tags, v.stance) == (
        "other", "other", None, ["livelihoods"], "neutral")


def test_a_topic_verdict_is_forgiving_in_the_same_way():
    t = classify.TopicVerdict.model_validate({
        "on_target": True, "match": 0.8, "confidence": 0.9, "topic": "philanthropy", "content_kind": "report",
        "is_news": True, "scope": "regional", "sentiment": "mixed", "summary": "s", "event_date": "2026-09"})
    assert (t.topic, t.content_kind, t.scope, t.sentiment, t.event_date) == ("other", "other", "national",
                                                                            "neutral", None)

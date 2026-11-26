"""The Jev client: what it sends, what it reads back, and that it never raises."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.core.config import Settings
from app.integrations import typesafe

KEY = "ts-secret-key"
QUESTIONS = {"route": {"type": "choice", "criteria": {"catalog": "x", "off_topic": "y"}}}
ANSWER = {
    "model": "jev-1.14.0",
    "usage": {"input_tokens": 120, "output_tokens": 4},
    "answers": {
        "route": {"type": "choice", "choice": "catalog", "confidence": 0.93,
                  "probabilities": {"catalog": 0.93, "off_topic": 0.07}},
        "ok": {"type": "noul", "noul": 0.81},
    },
}


@pytest.fixture
def settings():
    return Settings(_env_file=None, typesafe_api_key=KEY, jev_usd_per_mtok=0.05)


@pytest.fixture(autouse=True)
def generations(monkeypatch):
    seen = []
    monkeypatch.setattr(typesafe, "jev_generation", lambda name, **kw: seen.append((name, kw)))
    return seen


def _transport(handler):
    return httpx.MockTransport(handler)


def _decide(settings, handler, **kw):
    return typesafe.decide({"question": "q"}, QUESTIONS, name="jev_test", settings=settings,
                           transport=_transport(handler), **kw)


def test_a_200_is_read_into_a_decision(settings, generations):
    sent = {}

    def handler(request):
        sent["auth"] = request.headers["authorization"]
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json=ANSWER)

    decision = _decide(settings, handler)
    assert sent["auth"] == f"Bearer {KEY}"
    assert sent["body"] == {"state": {"question": "q"}, "model": "jev-latest", "questions": QUESTIONS}
    assert decision.choice("route") == ("catalog", 0.93, {"catalog": 0.93, "off_topic": 0.07})
    assert decision.noul("ok") == 0.81
    assert (decision.model, decision.input_tokens, decision.estimated) == ("jev-1.14.0", 120, False)
    assert decision.cost_usd == pytest.approx(120 * 0.05 / 1_000_000)
    assert [name for name, _ in generations] == ["jev_test"]


def test_an_unanswered_or_mistyped_question_reads_as_nothing(settings):
    decision = _decide(settings, lambda r: httpx.Response(200, json=ANSWER))
    assert decision.choice("ok") == (None, 0.0, {})
    assert decision.choice("missing") == (None, 0.0, {})
    assert decision.noul("route") is None


def test_odd_fields_read_as_nothing_rather_than_raise(settings):
    body = {"usage": "n/a", "answers": {
        "route": {"type": "choice", "choice": "catalog", "confidence": "high", "probabilities": {"catalog": "x"}},
        "skill": {"type": "choice", "choice": 3},
        "ok": {"type": "noul", "noul": "0.8"},
    }}
    decision = _decide(settings, lambda r: httpx.Response(200, json=body))
    assert decision.estimated is True
    assert decision.choice("route") == ("catalog", 0.0, {})
    assert decision.choice("skill") == (None, 0.0, {})
    assert decision.noul("ok") is None


async def test_the_async_call_reads_the_same_and_fails_the_same(settings, generations, caplog):
    def call(handler):
        return typesafe.adecide({"question": "q"}, QUESTIONS, name="jev_test", settings=settings,
                                transport=httpx.MockTransport(handler))

    decision = await call(lambda r: httpx.Response(200, json=ANSWER))
    assert decision.choice("route")[0] == "catalog" and [n for n, _ in generations] == ["jev_test"]
    assert await call(lambda r: httpx.Response(500)) is None
    assert KEY not in caplog.text
    assert await typesafe.adecide({}, QUESTIONS, name="x", settings=Settings(_env_file=None)) is None


def test_missing_usage_is_estimated_from_the_request(settings):
    body = {k: v for k, v in ANSWER.items() if k != "usage"}
    decision = _decide(settings, lambda r: httpx.Response(200, json=body))
    assert decision.estimated is True
    assert decision.input_tokens > 0


def test_trace_false_records_no_generation(settings, generations):
    _decide(settings, lambda r: httpx.Response(200, json=ANSWER), trace=False)
    assert generations == []


def test_no_key_makes_no_call():
    called = []
    decision = typesafe.decide({}, QUESTIONS, name="x", settings=Settings(_env_file=None),
                               transport=_transport(lambda r: called.append(1)))
    assert decision is None and called == []


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(401, json={"detail": "bad key"}),
    lambda r: httpx.Response(500),
    lambda r: httpx.Response(200, json={"no": "answers"}),
    lambda r: httpx.Response(200, content=b"not json"),
    lambda r: httpx.Response(200, json={"answers": ["route"]}),
    lambda r: httpx.Response(200, json=[1]),
])
def test_a_failure_is_none_and_never_logs_the_key(settings, handler, caplog):
    with caplog.at_level(logging.DEBUG):
        assert _decide(settings, handler) is None
    assert KEY not in caplog.text
    assert "jev jev_test failed" in caplog.text


def test_a_timeout_is_none(settings):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    assert _decide(settings, handler) is None


def test_a_call_is_a_generation_with_its_own_cost(monkeypatch):
    from contextlib import nullcontext

    import langfuse

    from app.integrations import tracing

    seen = {}

    class Client:
        def start_as_current_observation(self, **kw):
            seen.update(kw)
            return nullcontext()

    monkeypatch.setattr(tracing, "current_observation", lambda: None)
    monkeypatch.setattr(langfuse, "get_client", lambda: Client())
    decision = typesafe.Decision({"route": {}}, "jev-latest", 120, True, 90, 0.000005)
    tracing.jev_generation("jev_route_skill", state={"question": "q"}, decision=decision)
    assert seen["as_type"] == "generation" and seen["model"] == "jev-latest"
    assert seen["usage_details"] == {"input": 120} and seen["cost_details"] == {"input": 0.000005}
    assert seen["metadata"] == {"latency_ms": 90, "usage_estimated": True}


def test_a_generation_that_cannot_be_recorded_is_skipped(monkeypatch):
    import langfuse

    from app.integrations import tracing

    monkeypatch.setattr(tracing, "current_observation", lambda: None)
    monkeypatch.setattr(langfuse, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("no langfuse")))
    tracing.jev_generation("x", state={}, decision=typesafe.Decision({}, "m", 0, True, 0, 0.0))

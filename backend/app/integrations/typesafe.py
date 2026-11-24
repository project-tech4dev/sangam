"""TypeSafe's Jev: typed decisions with calibrated probabilities, one HTTP call for several questions."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.integrations.tracing import jev_generation

logger = logging.getLogger(__name__)

URL = "https://api.typesafe.ai/v1/systemone"
TIMEOUT_S = 3.0  # Jev answers in ~0.1-0.5 s; past this, the decision is not worth the wait
CHARS_PER_TOKEN = 4  # only when the response reports no usage


@dataclass(frozen=True, slots=True)
class Decision:
    answers: dict[str, dict]
    model: str
    input_tokens: int
    estimated: bool  # input_tokens came from the request's size, not from TypeSafe
    latency_ms: int
    cost_usd: float

    def choice(self, name: str) -> tuple[str | None, float, dict[str, float]]:
        """The chosen label, its confidence and every label's probability; (None, 0, {}) when unanswered."""
        answer = self.answers.get(name) or {}
        label = answer.get("choice")
        if answer.get("type") != "choice" or not isinstance(label, str):
            return None, 0.0, {}
        probabilities = answer.get("probabilities")
        probabilities = probabilities if isinstance(probabilities, dict) else {}
        return label, _number(answer.get("confidence")) or 0.0, {
            k: p for k, v in probabilities.items() if (p := _number(v)) is not None}

    def noul(self, name: str) -> float | None:
        answer = self.answers.get(name) or {}
        return _number(answer.get("noul")) if answer.get("type") == "noul" else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _decision(data: Any, body: dict, started: float, settings: Settings) -> Decision:
    """Raises on a reply that is not the documented shape; the caller turns that into None."""
    answers = data["answers"]
    if not isinstance(answers, dict):
        raise TypeError("answers is not an object")
    usage = data.get("usage")
    reported = usage.get("input_tokens") if isinstance(usage, dict) else None
    estimated = not isinstance(reported, int) or isinstance(reported, bool)
    tokens = len(json.dumps(body)) // CHARS_PER_TOKEN if estimated else reported
    return Decision(
        answers={k: v for k, v in answers.items() if isinstance(v, dict)},
        model=str(data.get("model") or settings.jev_model),
        input_tokens=tokens,
        estimated=estimated,
        latency_ms=round((time.perf_counter() - started) * 1000),
        cost_usd=tokens * settings.jev_usd_per_mtok / 1_000_000,
    )


def _failed(name: str, exc: Exception) -> None:
    logger.warning("jev %s failed: %s", name, type(exc).__name__)  # the type only: a message could echo the request


def decide(
    state: dict[str, Any],
    questions: dict[str, dict],
    *,
    name: str,
    settings: Settings,
    trace: bool = True,
    transport: httpx.BaseTransport | None = None,
) -> Decision | None:
    """Ask Jev; None with no key, on a timeout or on any error, since a decision must never break a turn."""
    if not settings.typesafe_api_key:
        return None
    body = {"state": state, "model": settings.jev_model, "questions": questions}
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=TIMEOUT_S, transport=transport) as client:
            response = client.post(URL, json=body, headers={"Authorization": f"Bearer {settings.typesafe_api_key}"})
        response.raise_for_status()
        decision = _decision(response.json(), body, started, settings)
    except Exception as exc:  # noqa: BLE001
        _failed(name, exc)
        return None
    if trace:
        jev_generation(name, state=state, decision=decision)
    return decision


async def adecide(
    state: dict[str, Any],
    questions: dict[str, dict],
    *,
    name: str,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Decision | None:
    """decide() for a hook on the event loop, where a blocking call would stall every other request."""
    if not settings.typesafe_api_key:
        return None
    body = {"state": state, "model": settings.jev_model, "questions": questions}
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
            response = await client.post(
                URL, json=body, headers={"Authorization": f"Bearer {settings.typesafe_api_key}"})
        response.raise_for_status()
        decision = _decision(response.json(), body, started, settings)
    except Exception as exc:  # noqa: BLE001
        _failed(name, exc)
        return None
    jev_generation(name, state=state, decision=decision)
    return decision

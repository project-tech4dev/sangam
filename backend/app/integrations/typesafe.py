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
        if answer.get("type") != "choice":
            return None, 0.0, {}
        return answer.get("choice"), float(answer.get("confidence") or 0.0), dict(answer.get("probabilities") or {})

    def noul(self, name: str) -> float | None:
        answer = self.answers.get(name) or {}
        return float(answer["noul"]) if answer.get("type") == "noul" and "noul" in answer else None


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
        data = response.json()
        answers = data["answers"]
    except Exception as exc:  # noqa: BLE001 - the type is enough; a message could echo the request
        logger.warning("jev %s failed: %s", name, type(exc).__name__)
        return None
    latency_ms = round((time.perf_counter() - started) * 1000)
    reported = (data.get("usage") or {}).get("input_tokens")
    tokens = int(reported) if isinstance(reported, int) else len(json.dumps(body)) // CHARS_PER_TOKEN
    decision = Decision(
        answers={k: v for k, v in answers.items() if isinstance(v, dict)},
        model=str(data.get("model") or settings.jev_model),
        input_tokens=tokens,
        estimated=not isinstance(reported, int),
        latency_ms=latency_ms,
        cost_usd=tokens * settings.jev_usd_per_mtok / 1_000_000,
    )
    if trace:
        jev_generation(name, state=state, decision=decision)
    return decision

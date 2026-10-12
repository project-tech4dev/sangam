"""The news verifier: a bounded deep agent that re-reads a borderline match before it is stored."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.ingest.adapters.tavily_news import Hit
from app.ingest.news.classify import EntityVerdict, _item, _prompt
from app.ingest.news.feeds import Subject, profile_for

# A run's checks share one agent; each check is a fresh ainvoke with no checkpointer, so nothing carries over.
RECURSION_LIMIT = 60


class Check(BaseModel):
    """What the verifier may change; the rest of the first read stands."""

    on_target: bool
    match: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    stance: Literal["positive", "neutral", "negative"]
    evidence: str = ""
    evidence_url: str | None = None

    _short = field_validator("evidence", mode="before")(lambda v: str(v or "")[:200])


def build_verifier(settings) -> Any:
    """Read-only by construction: two web-reading tools and the filesystem floor, no subagent, no checkpointer."""
    from deepagents import create_deep_agent
    from deepagents.backends.state import StateBackend

    from app.agent.harness import REQUIRED_MINIMUM, filesystem, install
    from app.agent.models import resolve_model
    from app.ingest.middleware import ReadingLimit, call_limit, fallback
    from app.ingest.tools.research_tools import read_page, search_public_sources
    from app.integrations.tracing import trace_config

    install()
    backend = StateBackend()
    agent = create_deep_agent(
        model=resolve_model(settings.research_model),
        tools=[read_page, search_public_sources],
        system_prompt=_prompt("verify"),
        backend=backend,
        middleware=[
            filesystem(backend, keep=REQUIRED_MINIMUM, evict=False),
            ReadingLimit(settings.news_verify_page_limit),
            call_limit(settings.news_verify_call_limit),
            *fallback(settings.research_model, settings.model),
        ],
        response_format=Check,
    )
    return agent.with_config({
        **trace_config(settings, name="sangam_news_verify", tags=("news", "verify", settings.research_model)),
        "recursion_limit": RECURSION_LIMIT,
    })


def _read(messages: list, url: str | None) -> bool:
    """Whether read_page actually returned text for `url` in this check."""
    if not url:
        return False
    calls = {tc["id"] for m in messages for tc in getattr(m, "tool_calls", None) or []
             if tc["name"] == "read_page" and str(tc["args"].get("url", "")).rstrip("/") == url.rstrip("/")}
    return any(getattr(m, "tool_call_id", None) in calls
               and not str(m.content).startswith(("REFUSED", "ERROR", "read_page failed", "No readable"))
               for m in messages)


async def verify(agent, subject: Subject, hit: Hit, first: EntityVerdict) -> EntityVerdict | None:
    """The checked verdict, or None when the agent ended without one; the first read then stands."""
    ask = (f"Organisation: {subject.name}. Who it is: {profile_for(subject)}\n\n{_item(hit)}\n\n"
           f"First read: on target {first.on_target}, match {first.match}, confidence {first.confidence}, "
           f"stance {first.stance}. {first.summary}")
    result = await agent.ainvoke({"messages": [("user", ask)]})
    check = result.get("structured_response")
    if not isinstance(check, Check):
        return None
    update = check.model_dump()
    # A page can carry text aimed at us; only a page actually read may move a story towards the public bar.
    raises = (check.match > first.match or check.confidence > first.confidence
              or (check.on_target and not first.on_target))
    if raises and not _read(result.get("messages", []), check.evidence_url):
        update.update(on_target=first.on_target, match=first.match, confidence=first.confidence,
                      evidence=f"{check.evidence} (raise not applied: no page read)")
    return first.model_copy(update={**update, "verified": True})

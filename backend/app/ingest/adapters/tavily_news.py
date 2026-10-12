"""Tavily search, the Media & Signals collector (spec D2). Social posts arrive only as Tavily returns them."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from app.ingest.news.links import is_facebook

API = "https://api.tavily.com/search"
SNIPPET_MAX = 1000  # D11: the snippet is kept; article text never is
TEXT_MAX = 8000


class SearchFailed(Exception):
    """Every attempt failed; the subject's watermark must not move."""


@dataclass(frozen=True)
class Hit:
    url: str
    title: str | None
    snippet: str
    text: str
    published: str | None
    query: str
    scope: str


async def search(client: httpx.AsyncClient, *, api_key: str, query: str, days: int, scope: str,
                 domains: tuple[str, ...] | None, attempts: int = 3, pause: float = 3.0) -> list[Hit]:
    body = {"query": query, "topic": "news", "days": days, "max_results": 20,
            "include_raw_content": True, "search_depth": "advanced"}
    if domains:
        body["include_domains"] = list(domains)
    error = "no attempt made"
    for attempt in range(attempts):
        try:
            r = await client.post(API, json=body, headers={"Authorization": f"Bearer {api_key}"}, timeout=120)
            if r.status_code == 200:
                return [
                    Hit(url=x["url"], title=x.get("title"), snippet=(x.get("content") or "")[:SNIPPET_MAX],
                        text=(x.get("raw_content") or x.get("content") or "")[:TEXT_MAX],
                        published=x.get("published_date"), query=query, scope=scope)
                    for x in r.json().get("results", []) if x.get("url") and not is_facebook(x["url"])
                ]
            error = f"{r.status_code} {r.text[:150]}"
        except httpx.HTTPError as exc:
            error = type(exc).__name__
        if attempt < attempts - 1:
            await asyncio.sleep(pause)
    raise SearchFailed(f"{query!r} ({scope}): {error}")

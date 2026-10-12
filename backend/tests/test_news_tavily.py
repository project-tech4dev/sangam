"""The collector: one Tavily search, retried, with Facebook dropped and the text trimmed."""

import json

import httpx
import pytest

from app.ingest.adapters import tavily_news


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_search_sends_the_window_and_returns_hits():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, json={"results": [
            {"url": "https://eastmojo.com/a", "title": "A", "content": "s" * 2000, "raw_content": "t" * 9000,
             "published_date": "Mon, 05 Oct 2026 10:00:00 GMT"},
            {"url": "https://www.facebook.com/x/posts/1", "title": "F", "content": "f"},
        ]})

    async with _client(handler) as c:
        hits = await tavily_news.search(c, api_key="k", query='"KABIL"', days=90, scope="open_web", domains=None,
                                        pause=0)
    assert seen["days"] == 90 and seen["topic"] == "news" and "include_domains" not in seen
    assert [h.url for h in hits] == ["https://eastmojo.com/a"]
    assert len(hits[0].snippet) == 1000 and len(hits[0].text) == 8000


async def test_it_retries_then_raises():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(502, text="bad gateway")

    async with _client(handler) as c:
        with pytest.raises(tavily_news.SearchFailed, match="502"):
            await tavily_news.search(c, api_key="k", query="q", days=7, scope="csr_ne", domains=("a.com",), pause=0)
    assert len(calls) == 3

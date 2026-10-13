"""Native web tools: search (Tavily) and URL fetching."""

from __future__ import annotations

import httpx
import trafilatura
from langchain_core.tools import BaseTool, tool
from langchain_tavily import TavilySearch

from app.core.egress import EgressRefused, guarded_client

FETCH_TIMEOUT_SECONDS = 20
USER_AGENT = "Mozilla/5.0 (compatible; DeepAgentApp/0.1; +https://github.com)"


def make_web_search(api_key: str, max_results: int = 5) -> BaseTool:
    return TavilySearch(max_results=max_results, tavily_api_key=api_key)


@tool
async def fetch_url(url: str) -> str:
    """Fetch a web page and return its readable text content.

    Use this to read the full content of a page found via web search, or any
    URL the user provides. Returns the extracted article text in full; a long page
    is saved to a file you page through with read_file. Do NOT use this on search-engine result pages (google.com/search
    etc.) — they block automated clients; use the web search tool instead.
    """
    # Never raise: a raised tool exception aborts the whole agent run, whereas
    # an error string lets the model see the failure and adapt.
    try:
        async with guarded_client(timeout=FETCH_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(url)
            response.raise_for_status()
    except EgressRefused as refused:
        return refused.reply
    except httpx.HTTPStatusError as exc:
        return (
            f"ERROR: {url} returned HTTP {exc.response.status_code} "
            f"{exc.response.reason_phrase}. The page could not be fetched — "
            f"try a different URL or approach."
        )
    except httpx.HTTPError as exc:
        return f"ERROR: fetching {url} failed ({type(exc).__name__}: {exc}). Try a different URL."
    except Exception as exc:  # noqa: BLE001 - an invalid URL must not end the run
        return f"fetch_url failed: {type(exc).__name__}: {exc}"

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().split("?")[0].endswith(".pdf"):
        return (
            f"{url} is a PDF ({len(response.content):,} bytes), which fetch_url cannot "
            f"read. Tell the user the link is a PDF and what you would need from it."
        )

    text = trafilatura.extract(response.text, url=url) or ""
    if not text.strip():
        return f"No readable text content could be extracted from {url}."
    return text

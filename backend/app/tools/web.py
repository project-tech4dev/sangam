"""Native web tools: search (Tavily) and URL fetching."""

from __future__ import annotations

import httpx
import trafilatura
from langchain_core.tools import BaseTool, tool
from langchain_tavily import TavilySearch

MAX_CONTENT_CHARS = 8_000
FETCH_TIMEOUT_SECONDS = 20
USER_AGENT = "Mozilla/5.0 (compatible; DeepAgentApp/0.1; +https://github.com)"


def make_web_search(api_key: str) -> BaseTool:
    return TavilySearch(max_results=5, tavily_api_key=api_key)


@tool
async def fetch_url(url: str) -> str:
    """Fetch a web page and return its readable text content.

    Use this to read the full content of a page found via web search, or any
    URL the user provides. Returns extracted article text, truncated to a safe
    length. Do NOT use this on search-engine result pages (google.com/search
    etc.) — they block automated clients; use the web search tool instead.
    """
    # Never raise: a raised tool exception aborts the whole agent run, whereas
    # an error string lets the model see the failure and adapt.
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return (
            f"ERROR: {url} returned HTTP {exc.response.status_code} "
            f"{exc.response.reason_phrase}. The page could not be fetched — "
            f"try a different URL or approach."
        )
    except httpx.HTTPError as exc:
        return f"ERROR: fetching {url} failed ({type(exc).__name__}: {exc}). Try a different URL."

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().split("?")[0].endswith(".pdf"):
        return (
            f"{url} is a PDF ({len(response.content):,} bytes), which fetch_url cannot "
            f"read directly. Use download_file to save it, then read_pdf to extract "
            f"its text."
        )

    text = trafilatura.extract(response.text, url=url) or ""
    if not text.strip():
        return f"No readable text content could be extracted from {url}."
    if len(text) > MAX_CONTENT_CHARS:
        return text[:MAX_CONTENT_CHARS] + f"\n\n[truncated at {MAX_CONTENT_CHARS} characters]"
    return text

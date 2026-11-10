"""Web search (Tavily), for Sangam Import's search_public_sources. Ask Sangam has no web tool."""

from __future__ import annotations

from langchain_core.tools import BaseTool
from langchain_tavily import TavilySearch


def make_web_search(api_key: str, max_results: int = 5) -> BaseTool:
    return TavilySearch(max_results=max_results, tavily_api_key=api_key)

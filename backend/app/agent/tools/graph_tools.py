"""Agent tool over the Graphiti knowledge graph (relationship facts)."""

from __future__ import annotations

from langchain_core.tools import tool

from app.core.config import get_settings
from app.integrations import graphiti


@tool
async def search_graph(query: str) -> str:
    """Search the knowledge graph for RELATIONSHIPS and connections between
    organisations, funders, people, and places — e.g. "what links KABIL to
    Tata Trusts?" or "which intermediaries co-implement with Axis Bank
    Foundation?".

    Use this for connection/relationship questions; use search_orgs /
    get_funder / get_fit_scores for factual record lookups. Returns temporal
    facts with [graph:ID] citation markers and validity dates.
    """
    try:
        if graphiti.client is None:
            reason = graphiti.graph_status(get_settings())
            return (
                "The knowledge graph is not available"
                + (f" ({reason})" if reason != "ok" else "")
                + ". Answer from the database tools instead, and say the "
                "relationship graph is not configured."
            )
        results = await graphiti.client.search(query, num_results=10)
        if not results:
            return f"No graph facts found for {query!r}."
        lines = []
        for edge in results:
            when = ""
            if getattr(edge, "valid_at", None):
                when = f" (valid from {edge.valid_at:%d %b %Y}"
                when += f" to {edge.invalid_at:%d %b %Y})" if getattr(edge, "invalid_at", None) else ", still current)"
            lines.append(f"[graph:{edge.uuid[:8]}] {edge.fact}{when}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"search_graph failed: {exc}"

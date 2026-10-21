"""Agent tool over the Graphiti knowledge graph (relationship facts)."""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool

from app.core.config import get_settings
from app.integrations import graphiti
from app.repositories import graph_search

EntityType = Literal[
    "Organization", "Funder", "GovernmentBody", "Program", "Scheme", "Location", "Theme", "PopulationGroup",
    "Person",
]
CITED = ("org:", "funder:")  # the catalog ids that are also Ask Sangam citation markers


def _end(end: dict | None) -> str:
    if not end:
        return "?"
    sangam_id = end.get("sangam_id") or ""
    cite = f" [{sangam_id}]" if sangam_id.startswith(CITED) else ""
    return f"{end['name']} ({end['type']}){cite}"


@tool
async def search_graph(query: str, types: list[EntityType] | None = None) -> str:
    """Search the knowledge graph for RELATIONSHIPS and connections between
    organisations, funders, government bodies, people, places, programmes,
    schemes, themes and population groups — e.g. "what
    links KABIL to Tata Trusts?" or "which intermediaries co-implement with Axis
    Bank Foundation?".

    The graph holds only these entity types: Organization, Funder,
    GovernmentBody, Program, Scheme, Location, Theme, PopulationGroup and Person
    (Scheme, Theme and PopulationGroup are Sangam's taxonomy); and only these
    relationships: FUNDS, PARTNERS_WITH, RUNS, IMPLEMENTS, WORKS_IN (role
    headquartered or operates), FOCUSES_ON, SERVES, LOCATED_IN, PART_OF, LEADS.
    Pass `types` to keep only facts between those entity types, e.g.
    ["Funder", "Organization"] for who funds or partners with whom, or
    ["Organization", "GovernmentBody"] for government partnerships.

    Use this for connection/relationship questions; use db_query for factual
    record lookups. Returns temporal facts with [graph:ID] citation markers,
    each end's type and, when the entity is in Sangam's catalog, its [org:N] or
    [funder:N] marker, and validity dates.
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
        facts = await graph_search.search(graphiti.client, query=query, group_id=None, limit=10, types=types)
        if not facts:
            return f"No graph facts found for {query!r}."
        lines = []
        for f in facts:
            when = ""
            if f["valid_at"]:
                when = f" (valid from {f['valid_at']:%d %b %Y}"
                when += f" to {f['invalid_at']:%d %b %Y})" if f["invalid_at"] else ", still current)"
            ends = f"{_end(f['source'])} -{f['name']}-> {_end(f['target'])}"
            lines.append(f"[graph:{f['uuid'][:8]}] {f['fact']}{when} — {ends}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"search_graph failed: {exc}"

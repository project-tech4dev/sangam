"""The single mount point for the REST API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    contacts,
    documents,
    funder_matches,
    funders,
    graph_search,
    ingest,
    me,
    meta,
    news,
    org_members,
    orgs,
    partner_lines,
    profiles,
    programs,
    rfps,
    scores,
    threads,
)

# Tag order here is the order resources appear in the OpenAPI docs.
OPENAPI_TAGS = [
    {"name": "orgs", "description": "CSO/NGO registry: profiles, identifiers, sectors, locations"},
    {"name": "funders", "description": "Funder profiles and their fit scores"},
    {"name": "profiles", "description": "One response per registry profile page"},
    {"name": "funder-matches", "description": "Funder Match: saved runs of an org against every funder"},
    {"name": "partner-lines", "description": "Funder partner lines: named partners and grants, from funder_activity"},
    {"name": "programs", "description": "Programs run by orgs or funders"},
    {"name": "rfps", "description": "Funding opportunities and org matches (RFP Watch)"},
    {"name": "contacts", "description": "People at orgs and funders"},
    {"name": "scores", "description": "Rubric-based funder-fit assessments and adjustment audit log"},
    {"name": "graph", "description": "Knowledge graph search over Graphiti (Neo4j)"},
    {"name": "ingest", "description": "Sangam Import: sources, run history and the review queue"},
    {"name": "meta", "description": "Shared vocabularies: tags and locations"},
    {"name": "me", "description": "The signed-in user and their org roles"},
    {"name": "threads", "description": "Ask Sangam chats: the caller's list and one chat's saved messages"},
]

api_router = APIRouter(prefix="/api")

for _router in (
    orgs.router,
    org_members.router,
    funders.router,
    profiles.router,
    funder_matches.router,
    partner_lines.router,
    programs.router,
    rfps.router,
    contacts.router,
    scores.router,
    meta.router,
    news.router,
    documents.router,
    graph_search.router,
    ingest.router,
    me.router,
    threads.router,
):
    api_router.include_router(_router)

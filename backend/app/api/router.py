"""The single mount point for the REST API.

`main.py` includes this one router, so adding a resource means adding its
module to `routes/` and one line here — the app module stays untouched.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    contacts,
    documents,
    funders,
    grants,
    meta,
    news,
    orgs,
    programs,
    rfps,
    scores,
)

# Tag order here is the order resources appear in the OpenAPI docs.
OPENAPI_TAGS = [
    {"name": "orgs", "description": "CSO/NGO registry: profiles, identifiers, sectors, locations"},
    {"name": "funders", "description": "Funder profiles and their fit scores"},
    {"name": "grants", "description": "Actual funding relationships between funders and orgs"},
    {"name": "programs", "description": "Programs run by orgs or funders"},
    {"name": "rfps", "description": "Funding opportunities and org matches (RFP Watch)"},
    {"name": "contacts", "description": "People at orgs and funders"},
    {"name": "scores", "description": "Rubric-based funder-fit assessments and adjustment audit log"},
    {"name": "meta", "description": "Shared vocabularies: tags and locations"},
]

api_router = APIRouter(prefix="/api")

for _router in (
    orgs.router,
    funders.router,
    grants.router,
    programs.router,
    rfps.router,
    contacts.router,
    scores.router,
    meta.router,
    news.router,
    documents.router,
):
    api_router.include_router(_router)

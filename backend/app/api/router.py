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

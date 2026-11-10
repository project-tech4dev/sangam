from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.db.pool import PoolDep
from app.repositories import partner_groups as repo
from app.schemas.partner_groups import PartnerGroupPage

UserDep = Annotated[UUID, Depends(get_current_user)]

router = APIRouter(tags=["partner-lines"])

PAGE = 20


async def _page(side: repo.Side, slug_or_id: str, pool, cursor: str | None) -> PartnerGroupPage:
    try:
        page = await repo.entity_groups(pool, side, slug_or_id, cursor=cursor, limit=PAGE)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if page is None:
        raise HTTPException(404, f"{side} {slug_or_id!r} not found")
    return PartnerGroupPage.model_validate(page)


@router.get("/funders/{slug_or_id}/partners", response_model=PartnerGroupPage,
            summary="A funder's partners, a page of partners at a time, each with all its lines")
async def funder_partners(slug_or_id: str, pool: PoolDep, user_id: UserDep,
                          cursor: str | None = None) -> PartnerGroupPage:
    return await _page("funder", slug_or_id, pool, cursor)


@router.get("/orgs/{slug_or_id}/funders", response_model=PartnerGroupPage,
            summary="The funders sources name for an org, a page of funders at a time")
async def org_funders(slug_or_id: str, pool: PoolDep, user_id: UserDep,
                      cursor: str | None = None) -> PartnerGroupPage:
    return await _page("org", slug_or_id, pool, cursor)

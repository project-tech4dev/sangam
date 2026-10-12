from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import PageParams
from app.api.routes import funders, news_stories, orgs, partner_lines, programs, scores
from app.core.security import get_current_user
from app.db.pool import PoolDep
from app.schemas.profiles import FunderProfile, OrgProfile

UserDep = Annotated[UUID, Depends(get_current_user)]

# One request per profile page: on Vercel each parallel call could land on its own cold instance.
router = APIRouter(tags=["profiles"])

FIFTY = PageParams(limit=50)


@router.get("/orgs/{slug_or_id}/profile", response_model=OrgProfile, summary="An organisation's profile page")
async def org_profile(slug_or_id: str, pool: PoolDep, user_id: UserDep) -> OrgProfile:
    org, funding, progs, fit, mentions = await asyncio.gather(
        orgs.get_org(slug_or_id, pool, user_id),
        partner_lines.list_partner_lines(pool, FIFTY, user_id, org=slug_or_id),
        programs.list_programs(pool, FIFTY, org=slug_or_id, user_id=user_id),
        scores.list_scores(pool, FIFTY, org=slug_or_id, user_id=user_id),
        _stories_or_empty(news_stories.org_news(slug_or_id, pool, limit=50)),
    )
    return OrgProfile(org=org, funding=funding.items, programs=progs.items, scores=fit.items, news=mentions)


@router.get("/funders/{slug_or_id}/profile", response_model=FunderProfile, summary="A funder's profile page")
async def funder_profile(slug_or_id: str, pool: PoolDep, user_id: UserDep) -> FunderProfile:
    funder, fit, partners, mentions, brief = await asyncio.gather(
        funders.get_funder(slug_or_id, pool, user_id),
        scores.list_scores(pool, FIFTY, funder=slug_or_id, user_id=user_id),
        partner_lines.list_partner_lines(pool, FIFTY, user_id, funder=slug_or_id),
        _stories_or_empty(news_stories.funder_news(slug_or_id, pool, limit=50)),
        _brief_or_none(slug_or_id, pool, user_id),
    )
    return FunderProfile(funder=funder, scores=fit.items, partners=partners, news=mentions, brief=brief)


async def _brief_or_none(slug_or_id: str, pool, user_id: UUID):
    # Most funders have no published brief; that is an empty field, not a failed page.
    try:
        return await funders.funder_brief(slug_or_id, pool, user_id)
    except HTTPException:
        return None


async def _stories_or_empty(page):
    # News is one tab: a failed read leaves it empty rather than failing the profile.
    try:
        return (await page).items
    except Exception:  # noqa: BLE001
        return []

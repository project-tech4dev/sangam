from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.db.pool import OwnerPoolDep, PoolDep
from app.integrations import storage
from app.repositories import news_stories as news_repo
from app.repositories import profile_facts
from app.schemas.documents import FileLinkOut
from app.schemas.profiles import FunderProfile, OrgProfile

logger = logging.getLogger(__name__)

UserDep = Annotated[UUID, Depends(get_current_user)]

# One request per profile page: on Vercel each parallel call could land on its own cold instance.
router = APIRouter(tags=["profiles"])

NEWS = 50


@router.get("/orgs/{slug_or_id}/profile", response_model=OrgProfile, summary="An organisation's profile page")
async def org_profile(slug_or_id: str, pool: PoolDep, owner: OwnerPoolDep, user_id: UserDep) -> OrgProfile:
    facts = await profile_facts.org_facts(pool, owner, slug_or_id)
    if facts is None:
        raise HTTPException(404, f"org {slug_or_id!r} not found")
    news, brief = await asyncio.gather(_news("org", facts.org.slug, pool), _brief(facts.org.slug))
    return OrgProfile(**facts.model_dump(), news=news, brief=brief)


@router.get("/funders/{slug_or_id}/profile", response_model=FunderProfile, summary="A funder's profile page")
async def funder_profile(slug_or_id: str, pool: PoolDep, owner: OwnerPoolDep,
                         user_id: UserDep) -> FunderProfile:
    facts = await profile_facts.funder_facts(pool, owner, slug_or_id)
    if facts is None:
        raise HTTPException(404, f"funder {slug_or_id!r} not found")
    news, brief = await asyncio.gather(_news("funder", facts.funder.slug, pool), _brief(facts.funder.slug))
    return FunderProfile(**facts.model_dump(), news=news, brief=brief)


async def _news(kind: Literal["org", "funder"], slug: str, pool) -> list:
    # News is one tab: a failed read leaves it empty rather than failing the profile.
    try:
        return (await news_repo.entity_news(pool, kind=kind, slug=slug, cursor=None, limit=NEWS))["items"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("profile news for %s failed: %s", slug, exc)
        return []


async def _brief(slug: str) -> FileLinkOut | None:
    # Most entities have no published brief, and a storage failure is an empty link, not a failed page.
    try:
        url = await storage.brief_link(slug)
    except Exception as exc:  # noqa: BLE001
        logger.warning("research brief lookup for %s failed: %s", slug, exc)
        return None
    return FileLinkOut(url=url, expires_in_seconds=storage.BRIEF_URL_TTL_SECONDS) if url else None

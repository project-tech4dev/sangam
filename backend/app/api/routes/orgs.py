from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import LegacyPageParams
from app.api.routes.funders import brief_for
from app.core.security import get_current_user
from app.db.pool import PoolDep
from app.repositories import orgs as repo
from app.schemas.orgs import OrgDetail, OrgListItem
from app.schemas.profiles import BriefLinkOut

router = APIRouter(prefix="/orgs", tags=["orgs"])


@router.get("", response_model=list[OrgListItem],
            summary="List organisations (legacy array shape)")
async def list_orgs(
    pool: PoolDep,
    page: LegacyPageParams = Depends(),
    tag: str | None = None,
    state: str | None = None,
    district: str | None = None,
    q: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> list[OrgListItem]:
    rows, _ = await repo.list_orgs(
        pool, limit=page.limit, offset=page.offset,
        tag=tag, state=state, district=district, q=q,
    )
    return [OrgListItem.model_validate(r) for r in rows]


@router.get("/{slug_or_id}", response_model=OrgDetail, summary="Organisation detail")
async def get_org(slug_or_id: str, pool: PoolDep, user_id: UUID = Depends(get_current_user)) -> OrgDetail:
    row = await repo.get_org(pool, slug_or_id)
    if row is None:
        raise HTTPException(404, f"org {slug_or_id!r} not found")
    return OrgDetail.model_validate(row)


@router.get("/{slug_or_id}/brief", response_model=BriefLinkOut, summary="A link to the rendered research brief")
async def org_brief(
    slug_or_id: str, pool: PoolDep, user_id: Annotated[UUID, Depends(get_current_user)],
) -> BriefLinkOut:
    return await brief_for(await repo.get_org(pool, slug_or_id), slug_or_id)

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import PageParams
from app.auth import get_current_user
from app.db import PoolDep
from app.repositories import grants as repo
from app.schemas.common import Page
from app.schemas.grants import GrantOut

router = APIRouter(prefix="/grants", tags=["grants"])


@router.get("", response_model=Page[GrantOut], summary="List funding relationships")
async def list_grants(
    pool: PoolDep,
    page: PageParams = Depends(),
    status: str | None = None,
    funder: str | None = None,
    org: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[GrantOut]:
    rows, total = await repo.list_grants(
        pool, limit=page.limit, offset=page.offset,
        status=status, funder=funder, org=org,
    )
    return Page(items=[GrantOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)


@router.get("/{grant_id}", response_model=GrantOut, summary="Grant detail")
async def get_grant(grant_id: int, pool: PoolDep, user_id: UUID = Depends(get_current_user)) -> GrantOut:
    row = await repo.get_grant(pool, grant_id)
    if row is None:
        raise HTTPException(404, f"grant {grant_id} not found")
    return GrantOut.model_validate(row)

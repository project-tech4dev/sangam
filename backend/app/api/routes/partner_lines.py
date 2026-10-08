from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import PageParams
from app.core.security import get_current_user
from app.db.pool import PoolDep
from app.repositories import partner_lines as repo
from app.schemas.common import Page
from app.schemas.partner_lines import PartnerLineOut

router = APIRouter(prefix="/partner-lines", tags=["partner-lines"])


@router.get("", response_model=Page[PartnerLineOut], summary="List funder partner lines (grants included)")
async def list_partner_lines(
    pool: PoolDep,
    page: Annotated[PageParams, Depends()],
    user_id: Annotated[UUID, Depends(get_current_user)],
    funder: str | None = None,
    org: str | None = None,
    status: str | None = None,
) -> Page[PartnerLineOut]:
    rows, total = await repo.list_partner_lines(
        pool, limit=page.limit, offset=page.offset, funder=funder, org=org, status=status,
    )
    return Page(items=[PartnerLineOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)


@router.get("/{line_id}", response_model=PartnerLineOut, summary="Partner line detail")
async def get_partner_line(
    line_id: int, pool: PoolDep, user_id: Annotated[UUID, Depends(get_current_user)],
) -> PartnerLineOut:
    row = await repo.get_partner_line(pool, line_id)
    if row is None:
        raise HTTPException(404, f"partner line {line_id} not found")
    return PartnerLineOut.model_validate(row)

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import LegacyPageParams
from app.core.security import get_current_user
from app.db.pool import PoolDep
from app.integrations import storage
from app.repositories import funders as repo
from app.schemas.funders import FunderDetail, FunderListItem, FunderScoreRow
from app.schemas.profiles import BriefLinkOut

router = APIRouter(prefix="/funders", tags=["funders"])


@router.get("", response_model=list[FunderListItem],
            summary="List funders (legacy array shape)")
async def list_funders(
    pool: PoolDep,
    page: LegacyPageParams = Depends(),
    tag: str | None = None,
    section_135: bool | None = None,
    user_id: UUID = Depends(get_current_user),
) -> list[FunderListItem]:
    rows, _ = await repo.list_funders(
        pool, limit=page.limit, offset=page.offset, tag=tag, section_135=section_135,
    )
    return [FunderListItem.model_validate(r) for r in rows]


@router.get("/{funder_id}/scores", response_model=list[FunderScoreRow],
            summary="Fit scores for a funder")
async def funder_scores(
    funder_id: int,
    pool: PoolDep,
    user_id: UUID = Depends(get_current_user),
) -> list[FunderScoreRow]:
    rows = await repo.funder_scores(pool, funder_id)
    if not rows:
        raise HTTPException(404, f"no scores for funder {funder_id}")
    return [FunderScoreRow.model_validate(r) for r in rows]


@router.get("/{slug_or_id}", response_model=FunderDetail, summary="Funder detail")
async def get_funder(
    slug_or_id: str,
    pool: PoolDep,
    user_id: UUID = Depends(get_current_user),
) -> FunderDetail:
    row = await repo.get_funder(pool, slug_or_id)
    if row is None:
        raise HTTPException(404, f"funder {slug_or_id!r} not found")
    return FunderDetail.model_validate(row)


@router.get("/{slug_or_id}/brief", response_model=BriefLinkOut,
            summary="A link to the rendered research brief")
async def funder_brief(
    slug_or_id: str, pool: PoolDep, user_id: Annotated[UUID, Depends(get_current_user)],
) -> BriefLinkOut:
    """404 rather than an empty answer: a funder in the catalog has not necessarily been researched."""
    return await brief_for(await repo.get_funder(pool, slug_or_id), slug_or_id)


async def brief_for(row: dict | None, asked: str) -> BriefLinkOut:
    """The brief of an org or funder row, looked up by its own slug; shared by both brief routes."""
    if row is None:
        raise HTTPException(404, f"{asked!r} not found")
    try:
        url = await storage.brief_link(row["slug"])
    except storage.BriefUnreachable as exc:
        raise HTTPException(502, "could not reach document storage") from exc
    if url is None:
        raise HTTPException(404, f"no research brief published for {row['slug']}")
    return BriefLinkOut(url=url, expires_in_seconds=storage.BRIEF_URL_TTL_SECONDS, slug=row["slug"], name=row["name"])

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import LegacyPageParams
from app.core.config import get_settings
from app.core.security import get_current_user
from app.db.pool import PoolDep
from app.integrations import storage
from app.repositories import funders as repo
from app.schemas.documents import FileLinkOut
from app.schemas.funders import FunderDetail, FunderListItem, FunderScoreRow

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


@router.get("/{slug_or_id}/brief", response_model=FileLinkOut,
            summary="A link to the rendered research brief")
async def funder_brief(
    slug_or_id: str,
    pool: PoolDep,
    user_id: UUID = Depends(get_current_user),
) -> FileLinkOut:
    """The markdown `make client-docs` renders, served from the bucket.

    404 rather than an empty answer when there is none: a funder in the
    catalog has not necessarily been researched, and a link to a brief that
    does not exist is worse than no link.
    """
    row = await repo.get_funder(pool, slug_or_id)
    if row is None:
        raise HTTPException(404, f"funder {slug_or_id!r} not found")
    key = storage.brief_key(row["slug"])
    if not get_settings().storage_enabled or await storage.stat(
        storage.SOURCE_ARCHIVE, key
    ) is None:
        raise HTTPException(404, f"no research brief published for {row['slug']}")
    url = await storage.signed_url(storage.SOURCE_ARCHIVE, key, storage.BRIEF_URL_TTL_SECONDS)
    if url is None:
        raise HTTPException(502, "could not reach document storage")
    return FileLinkOut(url=url, expires_in_seconds=storage.BRIEF_URL_TTL_SECONDS)

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import PageParams
from app.auth import get_current_user
from app.db import get_pool
from app.repositories import scores as repo
from app.schemas.common import Page
from app.schemas.scores import AdjustmentCreate, AdjustmentOut, FitScoreDetail, FitScoreOut

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("", response_model=Page[FitScoreOut], summary="List fit scores")
async def list_scores(
    page: PageParams = Depends(),
    org: str | None = None,
    funder: str | None = None,
    rubric: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[FitScoreOut]:
    rows, total = await repo.list_scores(get_pool(), limit=page.limit, offset=page.offset,
                                         org=org, funder=funder, rubric=rubric)
    return Page(items=[FitScoreOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)


@router.get("/{fit_score_id}", response_model=FitScoreDetail,
            summary="Fit score with criterion breakdown and adjustment log")
async def get_score(fit_score_id: int, user_id: UUID = Depends(get_current_user)) -> FitScoreDetail:
    row = await repo.get_score(get_pool(), fit_score_id)
    if row is None:
        raise HTTPException(404, f"fit score {fit_score_id} not found")
    return FitScoreDetail.model_validate(row)


@router.post("/{fit_score_id}/adjustments", response_model=AdjustmentOut, status_code=201,
             summary="Record a manual score adjustment (audit log)")
async def create_adjustment(
    fit_score_id: int, body: AdjustmentCreate, user_id: UUID = Depends(get_current_user)
) -> AdjustmentOut:
    row = await repo.create_adjustment(get_pool(), fit_score_id, body.model_dump(), user_id)
    if row is None:
        raise HTTPException(404, f"fit score {fit_score_id} not found")
    return AdjustmentOut.model_validate(row)

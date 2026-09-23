from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import PageParams
from app.auth import get_current_user
from app.db import get_pool
from app.repositories import meta as repo
from app.repositories import news as news_repo
from app.schemas.common import Page
from app.schemas.meta import LocationOut, TagOut
from app.schemas.news import StatsOut

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/stats", response_model=StatsOut, summary="Base coverage counts")
async def get_stats(user_id: UUID = Depends(get_current_user)) -> StatsOut:
    return StatsOut.model_validate(await news_repo.stats(get_pool()))


@router.get("/tags", response_model=Page[TagOut], summary="Tag vocabulary")
async def list_tags(
    page: PageParams = Depends(),
    kind: str | None = None,
    q: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[TagOut]:
    rows, total = await repo.list_tags(get_pool(), limit=page.limit, offset=page.offset,
                                       kind=kind, q=q)
    return Page(items=[TagOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)


@router.get("/locations", response_model=Page[LocationOut], summary="Location hierarchy")
async def list_locations(
    page: PageParams = Depends(),
    kind: str | None = None,
    parent: int | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[LocationOut]:
    rows, total = await repo.list_locations(get_pool(), limit=page.limit, offset=page.offset,
                                            kind=kind, parent=parent)
    return Page(items=[LocationOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)

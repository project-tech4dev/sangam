from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import PageParams
from app.auth import get_current_user
from app.db import PoolDep
from app.repositories import news as repo
from app.schemas.common import Page
from app.schemas.news import NewsOut

router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=Page[NewsOut], summary="News & signal mentions")
async def list_news(
    pool: PoolDep,
    page: PageParams = Depends(),
    org: str | None = None,
    funder: str | None = None,
    topic: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[NewsOut]:
    rows, total = await repo.list_news(pool, limit=page.limit, offset=page.offset,
                                       org=org, funder=funder, topic=topic)
    return Page(items=[NewsOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)

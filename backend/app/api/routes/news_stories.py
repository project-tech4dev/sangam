"""Reading stories (spec section 5). Signed-in lists run as the caller; profiles are public; hiding is staff's."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import CurrentUser, require_principal, require_staff
from app.db.pool import OwnerPoolDep, PoolDep
from app.repositories import news_stories as repo
from app.schemas.news_stories import HideIn, StoryPage

router = APIRouter(tags=["news"])
Limit = Annotated[int, Query(ge=1, le=50)]


def _bad_cursor(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/news/stories", response_model=StoryPage, summary="Stories by bucket, filter and search, keyset-paged")
async def list_stories(
    pool: PoolDep,
    owner: OwnerPoolDep,
    user: Annotated[CurrentUser, Depends(require_principal)],
    bucket: Literal["org", "funder", "general"] = "general",
    area: Literal["mine", "north_east", "all"] | None = None,
    org: str | None = None, funder: str | None = None, topic: str | None = None, sentiment: str | None = None,
    source: Literal["news", "social", "web"] | None = None, since: Literal["30d", "all"] = "all",
    q: str | None = None, cursor: str | None = None, limit: Limit = 20,
) -> StoryPage:
    f = repo.Filters(bucket=bucket, org=org, funder=funder, topic=topic, sentiment=sentiment, source=source,
                     since=since, q=q, area=area or ("all" if user.is_staff else "mine"), staff=user.is_staff)
    try:
        page = await repo.list_stories(pool, f, cursor=cursor, limit=limit)
    except ValueError as exc:
        raise _bad_cursor(exc) from exc
    # ingest_runs is not readable as the caller; the date it gives away is the header's anyway.
    return StoryPage.model_validate(page | {"last_pull": await repo.last_pull(owner)})


async def _entity(pool, kind: Literal["org", "funder"], slug: str, cursor: str | None, limit: int) -> StoryPage:
    try:
        return StoryPage.model_validate(await repo.entity_news(pool, kind=kind, slug=slug, cursor=cursor, limit=limit))
    except ValueError as exc:
        raise _bad_cursor(exc) from exc


@router.get("/orgs/{slug}/news", response_model=StoryPage, summary="An organisation's stories, newest first")
async def org_news(slug: str, pool: PoolDep, cursor: str | None = None, limit: Limit = 20) -> StoryPage:
    return await _entity(pool, "org", slug, cursor, limit)


@router.get("/funders/{slug}/news", response_model=StoryPage, summary="A funder's stories, newest first")
async def funder_news(slug: str, pool: PoolDep, cursor: str | None = None, limit: Limit = 20) -> StoryPage:
    return await _entity(pool, "funder", slug, cursor, limit)


@router.post("/news/stories/{story_id}/hide", status_code=204, summary="Hide a wrong match (staff)")
async def hide(story_id: int, body: HideIn, pool: OwnerPoolDep,
               user: Annotated[CurrentUser, Depends(require_staff)]) -> None:
    if (body.org_id is None) == (body.funder_id is None):
        raise HTTPException(status_code=422, detail="name exactly one of org_id or funder_id")
    if not await repo.hide(pool, story_id, org_id=body.org_id, funder_id=body.funder_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="no such match")

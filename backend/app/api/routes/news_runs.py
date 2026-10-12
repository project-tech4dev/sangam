"""The plan line on Scout's approval card for a news pull (spec 2b): staff only, writes nothing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_staff
from app.db.pool import OwnerPoolDep
from app.ingest.news import pipeline
from app.ingest.news.feeds import FEEDS, chosen_feeds
from app.schemas.news_runs import NewsPlanOut

router = APIRouter(prefix="/ingest/news-runs", tags=["ingest"], dependencies=[Depends(require_staff)])


@router.get("/plan", response_model=NewsPlanOut, summary="What a news pull would search and cost; writes nothing")
async def plan(pool: OwnerPoolDep, names: str = "", feeds: str = "") -> NewsPlanOut:
    """`names` and `feeds` as run_import_now takes them; both empty means everyone with the topic feeds."""
    wanted = [n.strip() for n in names.split(",") if n.strip()]
    try:
        keys = chosen_feeds(feeds)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    chosen = await pipeline.select(pool, wanted, keys)
    everyone = chosen.org_ids is None and chosen.funder_ids is None
    if wanted and not chosen.matched:
        return NewsPlanOut(everyone=False, subjects=0, newcomers=0, searches=0, cost_usd=0,
                           unmatched=chosen.unmatched)
    p = await pipeline.plan_for(pool, org_ids=chosen.org_ids, funder_ids=chosen.funder_ids, feeds=chosen.feeds)
    return NewsPlanOut(everyone=everyone, subjects=p.subjects, records=p.records, newcomers=p.newcomers,
                       searches=p.searches, checks=p.checks, cost_usd=p.cost_usd, matched=chosen.matched,
                       feeds=[FEEDS[k].label for k in chosen.feeds], unmatched=chosen.unmatched)

"""The plan line on Scout's approval card for a news pull (spec 2b): staff only, writes nothing."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require_staff
from app.db.pool import OwnerPoolDep
from app.ingest.news import pipeline
from app.schemas.news_runs import NewsPlanOut

router = APIRouter(prefix="/ingest/news-runs", tags=["ingest"], dependencies=[Depends(require_staff)])


@router.get("/plan", response_model=NewsPlanOut, summary="What a news pull would search and cost; writes nothing")
async def plan(pool: OwnerPoolDep, names: str = "") -> NewsPlanOut:
    """`names` as run_import_now's `funders`: comma-separated; empty means everyone with the topic feeds."""
    wanted = [n.strip() for n in names.split(",") if n.strip()]
    chosen = await pipeline.select(pool, wanted)
    everyone = chosen.org_ids is None and chosen.funder_ids is None
    if not (everyone or chosen.matched):
        return NewsPlanOut(everyone=False, subjects=0, newcomers=0, searches=0, cost_usd=0,
                           unmatched=chosen.unmatched)
    p = await pipeline.plan_for(pool, org_ids=chosen.org_ids, funder_ids=chosen.funder_ids, feeds=chosen.feeds)
    return NewsPlanOut(everyone=everyone, subjects=p.subjects, records=p.records, newcomers=p.newcomers,
                       searches=p.searches, cost_usd=p.cost_usd, matched=chosen.matched, unmatched=chosen.unmatched)

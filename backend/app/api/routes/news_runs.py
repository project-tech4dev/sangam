"""The plan line on Scout's approval card for a news pull (spec 2b): staff only, writes nothing."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.security import require_staff
from app.db.pool import OwnerPoolDep
from app.ingest.news import pipeline, windows
from app.schemas.news_runs import NewsPlanOut

router = APIRouter(prefix="/ingest/news-runs", tags=["ingest"], dependencies=[Depends(require_staff)])


@router.get("/plan", response_model=NewsPlanOut, summary="What a news pull would search and cost; writes nothing")
async def plan(pool: OwnerPoolDep, names: str = "") -> NewsPlanOut:
    """`names` as run_import_now's `funders`: comma-separated; empty means everyone with the topic feeds."""
    wanted = [n.strip() for n in names.split(",") if n.strip()]
    chosen = await pipeline.select(pool, wanted)
    everyone = chosen.org_ids is None and chosen.funder_ids is None
    subjects = await pipeline.plan_subjects(pool, org_ids=chosen.org_ids, funder_ids=chosen.funder_ids,
                                            feeds=chosen.feeds) if everyone or chosen.matched else []
    p = windows.plan(subjects, today=date.today(), settings=get_settings())
    return NewsPlanOut(everyone=everyone, subjects=p.subjects, records=sum(s.kind != "feed" for s in subjects), newcomers=p.newcomers, searches=p.searches,
                       cost_usd=p.cost_usd, matched=chosen.matched, unmatched=chosen.unmatched)

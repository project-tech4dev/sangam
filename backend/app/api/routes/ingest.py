from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user, require_staff, require_user
from app.db.pool import PoolDep
from app.ingest.sources import SOURCES
from app.repositories import ingest as repo
from app.schemas.ingest import (
    CoverageOut,
    QueueAnswerIn,
    QueueAnswerOut,
    QueueItemOut,
    ResearchOut,
    ReviewOut,
    RunItemOut,
    RunOut,
    SourceOut,
    SourceProposalOut,
    WorkbookOut,
)

router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_staff)])


@router.get("/sources", response_model=list[SourceOut], summary="Import sources and access rules")
async def list_sources(
    category: str | None = None,
    dispatchable: bool | None = None,
    user_id: UUID = Depends(get_current_user),
) -> list[SourceOut]:
    """The whole registry by default. It is ~74 entries, which is the same
    reason /orgs and /funders return everything rather than a page."""
    from app.ingest.runner import ADAPTERS

    chosen = list(SOURCES.values())
    if category:
        chosen = [s for s in chosen if category in {c.value for c in s.categories}]
    if dispatchable is not None:
        chosen = [s for s in chosen if s.dispatchable is dispatchable]
    return [
        SourceOut(
            key=s.key, name=s.name, host=s.host, access_rule=s.access_rule.value, basis=s.basis,
            categories=sorted(c.value for c in s.categories),
            yields=list(s.yields), dispatchable=s.dispatchable, has_adapter=s.key in ADAPTERS,
            robots_checked_at=s.robots_checked_at.isoformat() if s.robots_checked_at else None,
        )
        for s in chosen
    ]


@router.get("/proposals", response_model=list[SourceProposalOut],
            summary="Hosts read but not yet classified")
async def list_proposals(pool: PoolDep, limit: int = 50,
                         user_id: UUID = Depends(get_current_user)) -> list[SourceProposalOut]:
    return [SourceProposalOut.model_validate(r) for r in await repo.list_proposals(pool, limit=limit)]


@router.get("/runs", response_model=list[RunOut], summary="Recent import runs")
async def list_runs(pool: PoolDep, limit: int = 10,
                    user_id: UUID = Depends(get_current_user)) -> list[RunOut]:
    return [RunOut.model_validate(r) for r in await repo.list_runs(pool, limit=limit)]


@router.get("/runs/{run_id}", response_model=list[RunItemOut], summary="What one run did")
async def run_items(run_id: int, pool: PoolDep,
                    user_id: UUID = Depends(get_current_user)) -> list[RunItemOut]:
    if await repo.get_run(pool, run_id) is None:
        raise HTTPException(status_code=404, detail=f"no import run {run_id}")
    return [RunItemOut.model_validate(r) for r in await repo.list_items(pool, run_id)]


@router.get("/queue", response_model=list[QueueItemOut], summary="Names awaiting review")
async def queue(pool: PoolDep, limit: int = 50,
                user_id: UUID = Depends(get_current_user)) -> list[QueueItemOut]:
    return [QueueItemOut.model_validate(r) for r in await repo.list_queue(pool, limit=limit)]


@router.post("/queue/{item_id}", response_model=QueueAnswerOut, summary="Answer one name waiting for review")
async def answer_queue(item_id: int, body: QueueAnswerIn, pool: PoolDep,
                       user_id: UUID = Depends(require_user)) -> QueueAnswerOut:
    if body.answer == "same" and body.candidate_id is None:
        raise HTTPException(status_code=422, detail="'same' needs the candidate it is the same as")
    row = await repo.answer_queue(pool, item_id, same=body.answer == "same",
                                  candidate_id=body.candidate_id, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no pending name {item_id} with that candidate")
    return QueueAnswerOut.model_validate(row)


@router.get("/research", response_model=list[ResearchOut],
            summary="What the researchers have found and saved")
async def list_research(pool: PoolDep, limit: int = 50,
                        user_id: UUID = Depends(get_current_user)) -> list[ResearchOut]:
    return [ResearchOut.model_validate(r) for r in await repo.list_research(pool, limit=limit)]


@router.get("/research/{slug}/review", response_model=ReviewOut,
            summary="One organisation's answers, proof and questions, for the review card")
async def research_review(slug: str, user_id: UUID = Depends(get_current_user)) -> ReviewOut:
    from app.ingest.tools.catalog_tools import review_view

    view = await review_view(slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"no saved research for {slug!r}")
    return ReviewOut.model_validate(view)


@router.get("/workbooks", response_model=list[WorkbookOut], summary="The .xlsx workbooks in one bucket")
async def list_workbooks(bucket: str = "staff-sources", user_id: UUID = Depends(get_current_user)) -> list[WorkbookOut]:
    """Lets the spreadsheets card show the files at the first pause, before the agent has listed them."""
    from app.ingest.staff_sources import _BUCKET
    from app.integrations import storage

    if not _BUCKET.match(bucket):
        raise HTTPException(status_code=422, detail="not a bucket name")
    out = []
    for f in await storage.list_all(bucket):
        if not f["key"].lower().endswith(".xlsx"):
            continue
        folder, _, name = f["key"].rpartition("/")
        top = folder.split("/", 1)[0]
        label = SOURCES[top].name if top in SOURCES else (folder or "Not in a folder")
        out.append(WorkbookOut(
            path=storage.qualify(bucket, f["key"]), name=name, folder=folder, folder_label=label,
            size=f.get("size") if isinstance(f.get("size"), int) else None,
            updated_at=str(f["updated_at"])[:10] if f.get("updated_at") else None,
        ))
    return out


@router.get("/research/{slug}/coverage", response_model=CoverageOut,
            summary="What one entity's research found, per topic, and what saving it changed")
async def research_coverage(slug: str, user_id: UUID = Depends(get_current_user)) -> CoverageOut:
    from app.ingest.tools.catalog_tools import coverage_view

    view = await coverage_view(slug)
    if view is None:
        raise HTTPException(status_code=404, detail=f"no saved research for {slug!r}")
    return CoverageOut.model_validate(view)

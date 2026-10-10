from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.routes.threads import saved_messages
from app.core.security import CallerScope, get_current_user, request_scope, require_staff, require_user
from app.db.pool import OwnerPoolDep, PoolDep
from app.ingest.sources import SOURCES
from app.repositories import ingest as repo
from app.repositories import threads as threads_repo
from app.schemas.ingest import (
    CoverageOut,
    QueueAnswerIn,
    QueueAnswerOut,
    QueueItemOut,
    ResearchOut,
    ReviewOut,
    RunItemOut,
    RunOut,
    SaveIn,
    SaveOut,
    SourceOut,
    SourceProposalOut,
    UndoOut,
    WorkbookOut,
)
from app.schemas.threads import ThreadMessagesOut, ThreadOut

# Open to any signed-in user; the research routes are scoped to the caller, the rest are staff's.
router = APIRouter(prefix="/ingest", tags=["ingest"])
STAFF = [Depends(require_staff)]


@router.get("/sources", dependencies=STAFF, response_model=list[SourceOut], summary="Import sources and access rules")
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


@router.get("/proposals", dependencies=STAFF, response_model=list[SourceProposalOut],
            summary="Hosts read but not yet classified")
async def list_proposals(pool: PoolDep, limit: int = 50,
                         user_id: UUID = Depends(get_current_user)) -> list[SourceProposalOut]:
    return [SourceProposalOut.model_validate(r) for r in await repo.list_proposals(pool, limit=limit)]


@router.get("/runs", dependencies=STAFF, response_model=list[RunOut], summary="Recent import runs")
async def list_runs(pool: PoolDep, limit: int = 10,
                    user_id: UUID = Depends(get_current_user)) -> list[RunOut]:
    return [RunOut.model_validate(r) for r in await repo.list_runs(pool, limit=limit)]


@router.get("/runs/{run_id}", dependencies=STAFF, response_model=list[RunItemOut], summary="What one run did")
async def run_items(run_id: int, pool: PoolDep,
                    user_id: UUID = Depends(get_current_user)) -> list[RunItemOut]:
    if await repo.get_run(pool, run_id) is None:
        raise HTTPException(status_code=404, detail=f"no import run {run_id}")
    return [RunItemOut.model_validate(r) for r in await repo.list_items(pool, run_id)]


@router.get("/queue", dependencies=STAFF, response_model=list[QueueItemOut], summary="Names awaiting review")
async def queue(pool: PoolDep, limit: int = 50,
                user_id: UUID = Depends(get_current_user)) -> list[QueueItemOut]:
    return [QueueItemOut.model_validate(r) for r in await repo.list_queue(pool, limit=limit)]


@router.post("/queue/{item_id}", dependencies=STAFF, response_model=QueueAnswerOut, summary="Answer one name waiting for review")
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
async def list_research(pool: OwnerPoolDep, limit: int = 50,
                        caller: CallerScope = Depends(request_scope)) -> list[ResearchOut]:
    """Staff see everything; anyone else what they saved, plus research on the NGOs they steward."""
    mine = None if caller.is_staff else (caller.user_id, caller.steward_of)
    rows = await repo.list_research(pool, limit=limit, mine=mine)
    if not caller.is_staff:
        rows = [_public(r) for r in rows]
    return [ResearchOut.model_validate(r) for r in rows]


def _public(row: dict) -> dict:
    """A summary written from private findings is replaced, as the public brief replaces it."""
    from app.ingest.brief import PRIVATE_NOTE
    from app.ingest.source_guards import is_private_source

    sources = [u for u in row.get("sources_read") or [] if not is_private_source(u)]
    return {**row, "sources_read": sources, "summary": PRIVATE_NOTE if row.get("has_private") else row["summary"],
            "promotion_id": None, "saved_by": None}


@router.delete("/research/{slug}", dependencies=STAFF, status_code=204,
               summary="Delete research that was never saved, or whose saves were all undone")
async def delete_research(slug: str, pool: OwnerPoolDep) -> None:
    from app.ingest import undo

    async with pool.connection() as conn, conn.transaction():
        deleted = await undo.delete_research(conn, slug)
    if deleted is None:
        raise HTTPException(status_code=409, detail="This research is saved in Sangam. Undo the save first.")
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"no research for {slug!r}")


@router.post("/promotions/{promotion_id}/undo", dependencies=STAFF, response_model=UndoOut,
             summary="Undo one save: remove the rows it added and restore the ones it changed")
async def undo_promotion(promotion_id: int, pool: OwnerPoolDep, user_id: UUID = Depends(require_user)) -> UndoOut:
    from app.ingest import undo

    try:
        async with pool.connection() as conn, conn.transaction():
            done = await undo.undo(conn, promotion_id, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"no save {promotion_id}") from exc
    except undo.UndoRefused as exc:
        raise HTTPException(status_code=409, detail=f"Nothing was undone: {exc}.") from exc
    return UndoOut.model_validate(done)


@router.post("/research/{slug}/save", response_model=SaveOut,
             summary="Save one researched organisation to Sangam, with the person's answers to its questions")
async def save_research(slug: str, body: SaveIn, caller: CallerScope = Depends(request_scope)) -> SaveOut:
    from app.ingest.tools.catalog_tools import SaveRefused, save_to_catalog

    try:
        reports = await save_to_catalog(slug, caller, body.decisions)
    except SaveRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"no saved research for {slug!r}") from exc
    r = reports[0]
    return SaveOut(
        slug=r["slug"], entity=r.get("entity"),
        promotion_id=r.get("promotion_id") if caller.is_staff else None,
        written=sum(n for counts in r.get("written", {}).values() for status, n in counts.items()
                    if status in ("added", "updated")),
        held=len(r.get("held", [])), reasons=list(r.get("reasons", [])),
    )


@router.get("/research/{slug}/review", response_model=ReviewOut,
            summary="One organisation's answers, proof and questions, for the review card")
async def research_review(slug: str, caller: CallerScope = Depends(request_scope)) -> ReviewOut:
    from app.ingest.tools.catalog_tools import review_view

    view = await review_view(slug, caller)
    if view is None:
        raise HTTPException(status_code=404, detail=f"no saved research for {slug!r}")
    return ReviewOut.model_validate(view)


@router.get("/workbooks", dependencies=STAFF, response_model=list[WorkbookOut], summary="The .xlsx workbooks in one bucket")
async def list_workbooks(bucket: str = "staff-sources", user_id: UUID = Depends(get_current_user)) -> list[WorkbookOut]:
    """Lets the spreadsheets card show the files at the first pause, before the agent has listed them."""
    from app.integrations import storage

    # The staff bucket only, the same rule select_source_files applies.
    if bucket != storage.STAFF_SOURCES:
        raise HTTPException(status_code=422, detail=f"only the {storage.STAFF_SOURCES} bucket holds staff workbooks")
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
async def research_coverage(slug: str, caller: CallerScope = Depends(request_scope)) -> CoverageOut:
    from app.ingest.tools.catalog_tools import coverage_view

    view = await coverage_view(slug, caller)
    if view is None:
        raise HTTPException(status_code=404, detail=f"no saved research for {slug!r}")
    return CoverageOut.model_validate(view)


@router.get("/threads", response_model=list[ThreadOut], summary="The caller's own Import threads, newest first")
async def list_threads(pool: PoolDep, user_id: UUID = Depends(require_user)) -> list[ThreadOut]:
    rows = await threads_repo.list_threads(pool, user_id=user_id, kind="import")
    return [ThreadOut.model_validate(r) for r in rows]


@router.get("/threads/{thread_id}/messages", response_model=ThreadMessagesOut, summary="One Import thread's saved messages")
async def thread_messages(
    thread_id: str, request: Request, owner_pool: OwnerPoolDep, user_id: UUID = Depends(require_user)
) -> ThreadMessagesOut:
    # Only an Import thread: an Ask chat is read through its own graph, at /api/threads.
    if not thread_id.startswith("import-"):
        raise HTTPException(status_code=404, detail="Thread not found")
    return await saved_messages(request, owner_pool, user_id, thread_id, graph_name="ingest_graph")

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.routes.threads import saved_messages
from app.core.security import CurrentUser, require_principal
from app.db.pool import OwnerPoolDep, PoolDep
from app.proposals import gates, readiness, records, rubric, steps
from app.proposals import work as work_rules
from app.repositories import funder_matches
from app.repositories import proposals as repo
from app.repositories import threads as threads_repo
from app.schemas.proposals import (
    ProposalCreatedOut,
    ProposalCreateIn,
    ProposalItem,
    ProposalOut,
    SavedOut,
    TitleIn,
    WorkPatchIn,
)
from app.schemas.threads import ThreadMessagesOut

router = APIRouter(prefix="/proposals", tags=["proposals"])
Principal = Annotated[CurrentUser, Depends(require_principal)]
READ_ONLY = "You can read this proposal. Ask your organisation's admin to make changes."


def new_work(match: dict[str, Any], form: dict[str, Any] | None, org_name: str) -> dict[str, Any]:
    """Step 1's requirements from the saved match, and the funder's form when Sangam holds one."""
    built = gates.build(match["detail"], match["funder_type"], match["section_135_bound"])
    return {
        "rubric_version": rubric.RUBRIC_VERSION,
        "stage": 1,
        "requirements": built["requirements"],
        "requirement_cites": built["cites"],
        "gates": {},
        "earlier_phase": built["earlier_phase"],
        "match": {"id": match["id"], "score": match["score"], "run_at": match["run_at"].isoformat()},
        "template": ({"document_id": form["id"], "url": form["source_url"], "from": "sangam",
                      "read_at": form["fetched_at"].isoformat() if form["fetched_at"] else None} if form else None),
        "skipped_template": False,
        "sources": [],
        "style": rubric.default_style(org_name),
        "sections": {},
        "facts": {},
        "questions": {},
        "conflicts": [],
        "log": [],
        "versions": [],
    }


async def _readable(pool: PoolDep, proposal_id: int) -> dict:
    row = await repo.get(pool, proposal_id)
    if row is None:
        raise HTTPException(404, f"proposal {proposal_id} not found")
    return row


class _NotYet(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing


async def _save(pool: PoolDep, proposal_id: int, *, advancing: bool = False, **kwargs: Any) -> SavedOut:
    """Every write: refused for a reader, checked and logged by work.apply under the row lock."""
    row = await _readable(pool, proposal_id)
    if not row["can_edit"]:
        raise HTTPException(403, READ_ONLY)
    by = await repo.me(pool)
    # A corrected fact's fixed sentence must still trace, places included.
    correcting = any(path.endswith(".correct") for path in kwargs.get("changes") or {})
    districts = await records.districts(pool) if correcting else frozenset()

    def change(work: dict, title: str) -> work_rules.Applied:
        if advancing:
            stage = work.get("stage", 1)
            if missing := steps.exit_check(stage, work):
                raise _NotYet(missing)
            kwargs.update(changes={"stage": stage + 1}, advance=True)
        return work_rules.apply(work, by=by, title=title, districts=districts, **kwargs)

    try:
        applied = await repo.save(pool, proposal_id, change)
    except _NotYet as exc:
        raise HTTPException(409, {"message": "Not yet.", "missing": exc.missing}) from exc
    except work_rules.BadChange as exc:
        raise HTTPException(400, str(exc)) from exc
    except work_rules.StaleSection as exc:
        raise HTTPException(409, {"message": "This part changed since you opened it.", "section": exc.code,
                                  "current": exc.current, "changed_by": exc.changed_by}) from exc
    if applied is None:
        raise HTTPException(403, READ_ONLY)
    return SavedOut(summary=applied.summary, work=applied.work)


@router.get("", response_model=list[ProposalItem], summary="Proposals the caller may read, newest first")
async def list_proposals(pool: PoolDep, principal: Principal, org: str | None = None,
                         funder: int | None = None) -> list[ProposalItem]:
    org_id = None
    if org is not None:
        found = await funder_matches.find_org(pool, org)
        if found is None or not found["may_read"]:
            raise HTTPException(404, f"org {org} not found")
        org_id = found["id"]
    rows = await repo.list_proposals(pool, org_id=org_id, funder_id=funder)
    return [ProposalItem.model_validate(r) for r in rows]


@router.post("", response_model=ProposalCreatedOut, status_code=201, summary="Start a proposal from a saved match")
async def create_proposal(body: ProposalCreateIn, pool: PoolDep, principal: Principal) -> ProposalCreatedOut:
    found = await funder_matches.find_org(pool, body.org)
    if found is None or not found["may_read"]:
        raise HTTPException(404, f"org {body.org} not found")
    if not found["may_run"]:
        raise HTTPException(403, "Starting a proposal is for the organisation's admins and stewards.")
    match = await repo.match_for(pool, found["id"], body.funder_id)
    if match is None:
        raise HTTPException(409, "Run Funder Match first: this funder is not in the latest saved run.")
    work = new_work(match, await repo.funder_form(pool, body.funder_id), found["name"])
    pid = await repo.create(pool, org_id=found["id"], funder_id=body.funder_id, title=body.title.strip(),
                            work=work, summary=readiness.summary(work), created_by=principal.id)
    return ProposalCreatedOut(id=pid)


@router.get("/{proposal_id}", response_model=ProposalOut, summary="One proposal with its work")
async def get_proposal(proposal_id: int, pool: PoolDep, principal: Principal) -> ProposalOut:
    row = await _readable(pool, proposal_id)
    work = row["work"]
    sections = rubric.sections_for(bool(work.get("earlier_phase")), work.get("template"))
    tabs = [{"key": k, "label": label, "question": q} for k, label, q in rubric.TABS]
    # Recomputed, so a proposal saved before a summary field existed still shows it.
    return ProposalOut.model_validate({**row, "thread_id": repo.chat_thread(proposal_id, principal.id),
                                       "summary": readiness.summary(work),
                                       "sections": [s.out() for s in sections], "tabs": tabs})


@router.patch("/{proposal_id}", response_model=SavedOut, summary="Rename a proposal")
async def rename(proposal_id: int, body: TitleIn, pool: PoolDep, principal: Principal) -> SavedOut:
    return await _save(pool, proposal_id, changes={"title": body.title})


@router.patch("/{proposal_id}/work", response_model=SavedOut, summary="Save changes to a proposal, path by path")
async def patch_work(proposal_id: int, body: WorkPatchIn, pool: PoolDep, principal: Principal) -> SavedOut:
    return await _save(pool, proposal_id, changes=body.set, rev=body.rev)


@router.post("/{proposal_id}/advance", response_model=SavedOut, summary="Move to the next step, if nothing is missing")
async def advance(proposal_id: int, pool: PoolDep, principal: Principal) -> SavedOut:
    return await _save(pool, proposal_id, advancing=True)


@router.get("/{proposal_id}/messages", response_model=ThreadMessagesOut, summary="Your own chat about this proposal")
async def messages(proposal_id: int, request: Request, pool: PoolDep, owner_pool: OwnerPoolDep,
                   principal: Principal) -> ThreadMessagesOut:
    await _readable(pool, proposal_id)
    thread_id = repo.chat_thread(proposal_id, principal.id)
    if not await threads_repo.can_open(owner_pool, thread_id=thread_id, user_id=principal.id):
        return ThreadMessagesOut(thread_id=thread_id, messages=[])  # no question asked yet
    return await saved_messages(request, owner_pool, principal.id, thread_id, graph_name="proposal_graph")

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.routes.threads import saved_messages
from app.core.config import get_settings
from app.core.security import CurrentUser, require_principal
from app.db.pool import OwnerPoolDep, PoolDep
from app.integrations import storage
from app.proposals import assemble, gates, readiness, records, rubric, steps
from app.proposals import facts as fact_rules
from app.proposals import work as work_rules
from app.repositories import documents as documents_repo
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


async def _editable(pool: PoolDep, proposal_id: int) -> dict:
    row = await _readable(pool, proposal_id)
    if not row["can_edit"]:
        raise HTTPException(403, READ_ONLY)
    return row


class _NotYet(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing


async def _save(pool: PoolDep, proposal_id: int, *, advancing: bool = False, **kwargs: Any) -> SavedOut:
    """Every write: refused for a reader, checked and logged by work.apply under the row lock."""
    row = await _editable(pool, proposal_id)
    by = await repo.me(pool)
    changes = kwargs.get("changes") or {}
    picked = changes.get("sources")
    if (isinstance(picked, list) and all(isinstance(d, int) for d in picked)
            and set(picked) - await documents_repo.org_document_ids(pool, row["org"]["id"], picked)):
        raise HTTPException(422, "Only this organisation's own files can be ticked.")
    # A corrected fact's fixed sentence and a typed part must still trace, places included.
    tracing = any(path.endswith((".correct", ".text")) for path in changes)
    districts = await records.districts(pool) if tracing else frozenset()
    names = fact_rules.partner_names(row["work"], row["org"]["name"], row["funder"]["name"])
    graded = await _grade_done(row["work"], changes, kwargs.get("rev") or {})

    def change(work: dict, title: str) -> work_rules.Applied:
        if advancing:
            stage = work.get("stage", 1)
            if missing := steps.exit_check(stage, work):
                raise _NotYet(missing)
            kwargs.update(changes={"stage": stage + 1}, advance=True)
        return work_rules.apply(work, by=by, title=title, districts=districts, names=names, graded=graded,
                                **kwargs)

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


async def _grade_done(work: dict, changes: dict[str, Any],
                      rev: dict[str, int]) -> dict[str, list[str] | None]:
    """Each part marked Done, graded on its text; skipped when stale or already graded on that text."""
    from app.agent.models import resolve_model
    from app.proposals import grade

    out: dict[str, list[str] | None] = {}
    for path, value in changes.items():
        code = path.removeprefix("sections.").removesuffix(".done")
        if value is not True or path != f"sections.{code}.done":
            continue
        section = fact_rules.section_of(work, code)
        part = (work.get("sections") or {}).get(code) or {}
        text = changes.get(f"sections.{code}.text", part.get("text"))
        if section is None or not (text or "").strip() or rev.get(code) != part.get("rev", 0):
            continue
        if text == part.get("text") and part.get("missing") is not None:
            continue
        graded = await grade.grade(section, text, resolve_model(get_settings().utility_model))
        out[code] = graded.missing if graded else None
    return out


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
    tabs = [{"key": k, "label": label} for k, label in rubric.TABS]
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


def _names(row: dict) -> set[str]:
    """The names polish may not drop or change: the org, the funder and every partner or person in the facts."""
    facts = (row["work"].get("facts") or {}).values()
    named = [row["org"]["name"], row["funder"]["name"],
             *(f.get("value") for f in facts if f.get("kind") == "name" and fact_rules.is_live(f))]
    return {n for n in (fact_rules.norm(v) for v in named) if n}


@router.post("/{proposal_id}/polish", response_model=SavedOut,
             summary="Smooth the language; refused if any figure, place, name or gap changed")
async def polish_language(proposal_id: int, pool: PoolDep, principal: Principal) -> SavedOut:
    from app.agent.models import resolve_model  # the model stack loads only when it is used
    from app.proposals import polish

    row = await _editable(pool, proposal_id)
    work = row["work"]
    written = assemble.parts(work)
    if not written:
        raise HTTPException(409, {"message": "Nothing is written yet.", "differences": []})
    style = work.get("style") or rubric.default_style(row["org"]["name"])
    smoothed = await polish.smooth(written, style, resolve_model(get_settings().model))
    if smoothed is None:
        raise HTTPException(502, "Sangam couldn't smooth the language just now. Try again.")
    if changed := polish.differences(written, smoothed, districts=await records.districts(pool), names=_names(row)):
        raise HTTPException(409, {"message": "The smoothed wording changed what the proposal says, so it was not kept.",
                                  "differences": changed})
    held = work.get("sections") or {}
    polished = {"title": "Smoothed wording", "parts": {s.code: smoothed[s.code] for s, _ in written},
                "revs": {s.code: held[s.code].get("rev", 0) for s, _ in written},
                "at": datetime.now(UTC).isoformat(), "by": await repo.me(pool)}
    return await _save(pool, proposal_id, changes={"polished": polished}, via="polish")


@router.post("/{proposal_id}/versions", response_model=SavedOut, status_code=201,
             summary="Save the proposal as a Word file in the org's Doc Vault, as its next version")
async def save_version(proposal_id: int, pool: PoolDep, principal: Principal) -> SavedOut:
    row = await _editable(pool, proposal_id)
    if not get_settings().storage_enabled:
        raise HTTPException(503, "Saving Word files is not set up on this deployment.")
    work = row["work"]
    written = assemble.final(work)
    if not written:
        raise HTTPException(409, "Nothing is written yet.")
    n = len(work.get("versions") or []) + 1
    now = datetime.now(UTC)
    data = assemble.docx(row["title"], f"For {row['funder']['name']} from {row['org']['name']} · version {n} · "
                                       f"{now:%d %B %Y}", written)
    key = f"{row['org']['id']}/proposals/{proposal_id}/v{n}.docx"
    if await storage.upload(storage.ORG_VAULT, key, data, assemble.DOCX_TYPE) is None:
        raise HTTPException(502, "Could not reach document storage. Try again.")
    document_id = await repo.insert_draft(
        pool, org_id=row["org"]["id"], title=f"{row['title']}, version {n}",
        storage_path=storage.qualify(storage.ORG_VAULT, key), content_hash=storage.content_hash(data),
        content_md="\n\n".join(f"## {s.label}\n\n{text}" for s, text in written), uploaded_by=principal.id)
    entry = {"n": n, "title": f"Version {n}", "document_id": document_id, "at": now.isoformat(),
             "by": await repo.me(pool), "facts_snapshot": assemble.snapshot(work)}
    return await _save(pool, proposal_id, changes={"versions": [*(work.get("versions") or []), entry]}, via="version")


@router.get("/{proposal_id}/messages", response_model=ThreadMessagesOut, summary="Your own chat about this proposal")
async def messages(proposal_id: int, request: Request, pool: PoolDep, owner_pool: OwnerPoolDep,
                   principal: Principal) -> ThreadMessagesOut:
    await _readable(pool, proposal_id)
    thread_id = repo.chat_thread(proposal_id, principal.id)
    if not await threads_repo.can_open(owner_pool, thread_id=thread_id, user_id=principal.id):
        return ThreadMessagesOut(thread_id=thread_id, messages=[])  # no question asked yet
    return await saved_messages(request, owner_pool, principal.id, thread_id, graph_name="proposal_graph")

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.routes.threads import saved_messages
from app.core.config import get_settings
from app.core.lifespan import get_graph
from app.core.security import (
    CurrentUser,
    caller_scope,
    chat_proposal,
    chat_scope,
    chat_user_id,
    require_principal,
)
from app.db.pool import OwnerPoolDep, PoolDep
from app.integrations import storage
from app.proposals import assemble, context, fill, form, gates, readiness, records, research, rubric, steps
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
    ResearchAnglesOut,
    SavedOut,
    TitleIn,
    VersionIn,
    WorkPatchIn,
)
from app.schemas.threads import ThreadMessagesOut

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))  # a byline date is the date in India, where the proposal is sent from

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


class _Refused(Exception):
    """Inside the row lock: the change cannot be made as things stand, a 409."""


class _NotYet(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing


async def _save(pool: PoolDep, proposal_id: int, *, advancing: bool = False, to: int | None = None, **kwargs: Any) -> SavedOut:
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
            target = to or stage + 1
            if target <= stage:
                raise work_rules.BadChange("a step is moved back by PATCH /work")
            if missing := steps.blocking(work, target):
                raise _NotYet(missing)
            kwargs.update(changes={"stage": target}, advance=True)
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
    tabs = [{"key": k, "label": label, "step": rubric.stage_of(k)} for k, label in rubric.TABS]
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


@router.post("/{proposal_id}/advance", response_model=SavedOut,
             summary="Move forward to step `to` (default the next), if no step on the way has anything missing")
async def advance(proposal_id: int, pool: PoolDep, principal: Principal,
                  to: int | None = Query(None, ge=1, le=steps.LAST)) -> SavedOut:
    return await _save(pool, proposal_id, advancing=True, to=to)


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


@router.get("/{proposal_id}/research/angles", response_model=ResearchAnglesOut,
            summary="What research would look into from the case, for the person to edit before searching")
async def research_angles(proposal_id: int, pool: PoolDep, principal: Principal) -> ResearchAnglesOut:
    from app.agent.models import resolve_model  # the model stack loads only when it is used

    row = await _editable(pool, proposal_id)
    if missing := research.not_ready(row["work"]):
        raise HTTPException(409, {"message": "Not yet.", "missing": missing})
    try:
        kept, dropped = await research.angles(row["work"], resolve_model(get_settings().utility_model), _names(row))
    except Exception as exc:
        logger.warning("research angles for proposal %s failed (%s)", proposal_id, type(exc).__name__)
        raise HTTPException(502, "Sangam couldn't read your case just now. Try again.") from exc
    return ResearchAnglesOut(angles=kept, dropped=dropped)


@router.post("/{proposal_id}/research", response_model=SavedOut, status_code=202,
             summary="Start secondary research: the brief and the public facts, run in the background")
async def start_research(proposal_id: int, request: Request, pool: PoolDep, owner: OwnerPoolDep,
                         principal: Principal) -> SavedOut:
    row = await _editable(pool, proposal_id)
    if early := steps.too_early("read_files", int(row["work"].get("stage") or 1)):
        raise HTTPException(409, early)
    from app.proposals import readers

    # The readers are built with the agents, on first use: after a restart no chat may have built them yet.
    await get_graph(request.app, "proposal_graph")

    # The readers' tools find the proposal and the caller the way a chat turn sets them; the task copies them.
    chat_user_id.set(principal.id)
    chat_scope.set(await caller_scope(owner, principal))
    chat_proposal.set(proposal_id)
    p = await context.current()
    if p is None:
        raise HTTPException(404, f"proposal {proposal_id} not found")
    try:
        await readers.search(p)
    except readers.Busy as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(503, str(exc)) from exc
    saved = await repo.get(pool, proposal_id)
    return SavedOut(summary=readiness.summary(saved["work"]), work=saved["work"])


@router.delete("/{proposal_id}/research", response_model=SavedOut,
               summary="Delete secondary research: its brief, asks and the public facts no part cites")
async def delete_research(proposal_id: int, pool: PoolDep, principal: Principal) -> SavedOut:
    await _editable(pool, proposal_id)
    by = await repo.me(pool)

    def change(work: dict, title: str) -> work_rules.Applied:
        if ((work.get("readers") or {}).get("public") or {}).get("status") == "running":
            raise _Refused("A search is running. Try when it's done.")
        if not (changes := research.reset(work)):
            raise _Refused("There is no secondary research to delete.")
        return work_rules.apply(work, changes, by=by, via=work_rules.RESET, reason="deleting secondary research",
                                title=title)

    try:
        applied = await repo.save(pool, proposal_id, change)
    except _Refused as exc:
        raise HTTPException(409, str(exc)) from exc
    except work_rules.BadChange as exc:
        raise HTTPException(400, str(exc)) from exc
    if applied is None:
        raise HTTPException(403, READ_ONLY)
    return SavedOut(summary=applied.summary, work=applied.work)


@router.post("/{proposal_id}/versions", response_model=SavedOut, status_code=201,
             summary="Save the proposal as a Word file in the org's Doc Vault, as its next version")
async def save_version(proposal_id: int, pool: PoolDep, principal: Principal, body: VersionIn | None = None) -> SavedOut:
    row = await _editable(pool, proposal_id)
    if not get_settings().storage_enabled:
        raise HTTPException(503, "Saving Word files is not set up on this deployment.")
    work = row["work"]
    written = assemble.final(work)
    if not written:
        raise HTTPException(409, "Nothing is written yet.")
    n = len(work.get("versions") or []) + 1
    now = datetime.now(UTC)
    funder = row["funder"]["name"]
    byline = f"For {funder} from {row['org']['name']} · version {n} · {now.astimezone(IST):%d %B %Y}"
    changes: dict[str, Any] = {}
    entry: dict[str, Any] = {"title": f"Version {n}"}
    named = f"version {n}"
    if body is not None and body.shape == "form":
        outline, filled = await _fill_form(pool, proposal_id, row, written)
        if outline is not (work.get("template") or {}).get("outline"):
            changes["template.outline"] = outline
        laid = fill.outline(filled)
        headed = [(heading, text) for heading, text, _ in laid]
        data = assemble.form_docx(row["title"], f"{byline} · in the {funder} form", laid)
        named = f"version {n}, in the {funder} form"
        entry = {"title": f"V{named[1:]}", "shape": "form", "report": fill.report(filled)}
    else:
        headed = [(s.label, text) for s, text in written]
        data = assemble.docx(row["title"], byline, written)
    key = f"{row['org']['id']}/proposals/{proposal_id}/v{n}.docx"
    if await storage.upload(storage.ORG_VAULT, key, data, assemble.DOCX_TYPE) is None:
        raise HTTPException(502, "Could not reach document storage. Try again.")
    document_id = await repo.insert_draft(
        pool, org_id=row["org"]["id"], title=f"{row['title']}, {named}",
        storage_path=storage.qualify(storage.ORG_VAULT, key), content_hash=storage.content_hash(data),
        content_md="\n\n".join(f"## {heading}\n\n{text}" for heading, text in headed), uploaded_by=principal.id)
    entry = {"n": n, **entry, "document_id": document_id, "at": now.isoformat(), "by": await repo.me(pool),
             "facts_snapshot": assemble.snapshot(work)}
    changes["versions"] = [*(work.get("versions") or []), entry]
    return await _save(pool, proposal_id, changes=changes, via="version")


async def _fill_form(pool: PoolDep, proposal_id: int, row: dict, written: list) -> tuple[dict, list[fill.Filled]]:
    """The funder's form, read once and kept, with every heading filled from the written parts or marked."""
    from app.agent.models import resolve_model  # the model stack loads only when it is used

    work, settings = row["work"], get_settings()
    template = work.get("template")
    if not template or work.get("skipped_template"):
        raise HTTPException(409, "No funder's form was uploaded in step 2.")
    outline = template.get("outline")
    if not outline or outline.get("document_id") != template.get("document_id"):
        try:
            outline = await form.read(pool, template, row["org"]["id"], resolve_model(settings.research_model))
        except form.Unreadable as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            logger.warning("reading the form of proposal %s failed (%s)", proposal_id, type(exc).__name__)
            raise HTTPException(502, "Sangam couldn't read the funder's form just now. Try again.") from exc
    parts = {s.code: text for s, text in written}
    style = work.get("style") or rubric.default_style(row["org"]["name"])
    about = f"Organisation name: {row['org']['name']}\nCountry: India"
    answers = await fill.fill(outline["headings"], parts, style, resolve_model(settings.model), about)
    filled = fill.resolve(outline["headings"], parts, answers, earlier_phase=bool(work.get("earlier_phase")),
                          about=about, districts=await records.districts(pool), names=_names(row))
    return outline, filled


@router.get("/{proposal_id}/messages", response_model=ThreadMessagesOut, summary="Your own chat about this proposal")
async def messages(proposal_id: int, request: Request, pool: PoolDep, owner_pool: OwnerPoolDep,
                   principal: Principal) -> ThreadMessagesOut:
    await _readable(pool, proposal_id)
    thread_id = repo.chat_thread(proposal_id, principal.id)
    if not await threads_repo.can_open(owner_pool, thread_id=thread_id, user_id=principal.id):
        return ThreadMessagesOut(thread_id=thread_id, messages=[])  # no question asked yet
    return await saved_messages(request, owner_pool, principal.id, thread_id, graph_name="proposal_graph")

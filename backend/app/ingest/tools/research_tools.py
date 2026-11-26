"""The research path: search, a page, a file, a PDF — each gated on access.

The pipeline adapters handle the two sources we enumerate. These are for the
research the hand-vetted sheets did by hand: open the funder's CSR report, read
the pages that carry the figures, quote the sentence. `record_findings` keeps each
fact as it is found and `save_research` ends the path: the only write, of findings,
not catalog rows.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from langchain_tavily import TavilySearch
from pydantic import ValidationError

from app.core import extract
from app.core.config import get_settings
from app.core.extract import extract_pdf_text
from app.db.pool import get_pool
from app.ingest.brief import CARRIED, fact_key, merge_findings, publish, rows_for
from app.ingest.caller import scope, staff_only
from app.ingest.catalog.promote import org_match
from app.ingest.catalog.promote_records import MERGEABLE
from app.ingest.catalog.writer import slugify
from app.ingest.reading import snapshots
from app.ingest.reading.access import check_url
from app.ingest.reading.fetch import downloads_dir, fetch_document_file, read_page_text
from app.ingest.reading.staff_sources import is_staff_source_url
from app.ingest.research import draft
from app.ingest.research.contract import quoted_only, unanswered
from app.ingest.research.expectations import concepts_for
from app.ingest.research.finding_types import SCHEMA_VERSION, STORED
from app.ingest.research.findings import EntityResearch
from app.integrations.storage import safe_name

logger = logging.getLogger(__name__)


def make_web_search(api_key: str, max_results: int = 5) -> BaseTool:
    return TavilySearch(max_results=max_results, tavily_api_key=api_key)


@tool
async def search_public_sources(query: str, max_results: int = 6) -> str:
    """Search the public web for a funder's disclosures, and say which hits may be read.

    This is how you find a CSR report, an annual report or a BRSR filing before
    reading it. Search widely — the search itself reads nothing — but note the
    marker on each result: a hit on a HELD source is a dead end, not a target.
    Never work around one by looking for a cache, a mirror or a republisher.

    Good queries follow the source's own language:
        "<company>" CSR annual report FY2024-25
        "<company>" implementing agency
        site:<company-domain> "impact assessment"
        "<partner NGO>" "<company>"

    Args:
        query: the search string, quoted as you would type it.
        max_results: 3-10. Keep it small and search again with a sharper query.
    """
    settings = get_settings()
    if not settings.tavily_api_key:
        return (
            "SEARCH UNAVAILABLE: no TAVILY_API_KEY is configured, so nothing can be "
            "discovered. Ask the user for a URL instead, and say why."
        )
    try:
        # max_results is a constructor argument, not an invoke one: passing it in
        # the payload is silently ignored and the default is used.
        search = make_web_search(settings.tavily_api_key, max_results=max(3, min(max_results, 10)))
        raw = await search.ainvoke({"query": query})
    except Exception as exc:  # noqa: BLE001 - a failed search must not end the run
        return f"search failed: {type(exc).__name__}: {exc}"

    try:
        results = raw.get("results", []) if isinstance(raw, dict) else raw
        # Tavily can answer with a bare string instead of a result list. Iterating that
        # yields characters, and the AttributeError ended the whole run rather than the turn.
        if not isinstance(results, list):
            return f"search returned {type(results).__name__}, not results, for {query!r}: {str(results)[:300]}"
        results = [r for r in results if isinstance(r, dict)]
        if not results:
            return f"No results for {query!r}. Try the funder's own domain, or different wording."
        lines = [f"{len(results)} results for {query!r}:"]
        shown = results[:max_results]
        # At once: each check is DNS and robots.txt, and in turn ten of them took ~30 s against Tavily's ~3 s.
        refusals = await asyncio.gather(*(check_url(r.get("url", "")) for r in shown))
        for r, refusal in zip(shown, refusals, strict=True):
            url = r.get("url", "")
            mark = "READABLE" if refusal is None else "HELD"
            lines.append(f"\n[{mark}] {r.get('title', '(no title)')}\n  {url}")
            if refusal:
                lines.append(f"  why held: {refusal[:180]}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 - errors are return values
        return f"search_public_sources failed: {type(exc).__name__}: {exc}"


@tool
async def read_page(url: str) -> str:
    """Read a web page as text, if Sangam is allowed to read it.

    Use this for a funder's CSR page, an about page, a press release — anything
    the checklist needs that is not already covered by a source adapter. The URL
    is checked against the source registry and the site's robots.txt BEFORE it is
    fetched: a refusal is a final answer, not an obstacle to route around. Quote
    the sentence you rely on; the importer verifies quotes against this text.

    Give.do's /discover/ pages, GuideStar India's search API and the team's research
    repository at its pinned commit are readable on those paths only; their text
    opens with a banner saying how to label every value from it. Every redirect
    is checked too: a REFUSED that names a redirect is still final.
    """
    try:
        current = draft.CURRENT.get()
        return await read_page_text(url, current.slug if current else None)
    except Exception as exc:  # noqa: BLE001 - errors are return values
        return f"read_page failed: {type(exc).__name__}: {exc}"


@tool
async def fetch_document(url: str, filename: str | None = None) -> str:
    """Download a PDF, Word file or other document, if Sangam is allowed to read it.

    CSR impact reports, BRSR filings and annual reports are PDFs — this is how
    the figures in them are reached. Saves the file and returns its name; read it
    with read_document_pages. Access is checked before anything is fetched.
    """
    try:
        current = draft.CURRENT.get()
        return await fetch_document_file(url, filename, current.slug if current else None)
    except Exception as exc:  # noqa: BLE001 - errors are return values
        return f"fetch_document failed: {type(exc).__name__}: {exc}"


FIND_MAX_HITS = 30


def _find_pages(filename: str, destination: Path, find: str) -> str:
    """Pages (or Word paragraphs) naming any of the |-separated terms, one line each, so a report is read where it says it."""
    terms = [t for t in (" ".join(t.split()).lower() for t in find.split("|")) if t]
    if not terms:
        return "ERROR: find needs at least one word, e.g. find='CSR obligation|Annexure II'."
    word = destination.suffix.lower() == ".docx"
    try:
        if word:
            (hits, total), blank, unit = extract.find_in_docx(destination.read_bytes(), terms), 0, "paragraph"
        else:
            hits, total, blank = extract.find_in_pdf(destination, terms)
            unit = "page"
    except Exception as exc:  # noqa: BLE001 - a damaged file raises many types
        return f"ERROR: {filename} could not be searched ({type(exc).__name__}: {exc})."
    if total and blank == total:
        return (f"{filename} has {total} pages and none has text: it is scanned and cannot be searched. "
                f"Save a gap with reason 'blocked' (scanned PDF); do not report the figure as not stated.")
    scanned = f"\n{blank} of {total} pages have no text (scanned) and were not searched." if blank else ""
    if not hits:
        return f"No {unit} of {filename} ({total} {unit}s) mentions {find!r}. Try other words.{scanned}"
    lines = [f"{unit} {n}: {snippet}" for n, snippet in hits[:FIND_MAX_HITS]]
    if len(hits) > FIND_MAX_HITS:
        lines.append(f"… and {len(hits) - FIND_MAX_HITS} more {unit}s; narrow the words to see them.")
    return (f"[{filename}: {total} {unit}s, {len(hits)} mention {find!r}]\n" + "\n".join(lines)
            + f"\nRead the {unit}s you need with start_page and end_page; a snippet is not a quote.{scanned}")


@tool
def read_document_pages(
    filename: str, start_page: int = 1, end_page: int | None = None, find: str | None = None
) -> str:
    """Read text from a downloaded PDF, a page range at a time, or a Word (.docx) file by paragraphs.

    Pages are 1-indexed, and in a Word file start_page and end_page count paragraphs; omit end_page to read to the end. A long result is saved
    to a file you page through with read_file. A scanned PDF has
    no text layer and returns nothing: say so rather than guessing at its contents.

    In a long report, search before reading: find="CSR obligation|Annexure II|Form CSR-2" returns
    only the page numbers whose text names any of the |-separated words (case does not matter), one
    line each, and ignores start_page and end_page. Then read those pages. Quote only from a page you
    read, never from a find line.
    """
    destination = downloads_dir() / safe_name(filename)
    if not destination.exists():
        available = ", ".join(sorted(p.name for p in downloads_dir().iterdir())) or "(none)"
        return f"ERROR: {filename} is not in the downloads folder. Available: {available}"
    if find is not None:
        return _find_pages(filename, destination, find)
    if destination.suffix.lower() == ".docx":
        try:
            text, total = extract.docx_range(destination.read_bytes(), start_page, end_page)
        except Exception as exc:  # noqa: BLE001 - a damaged file raises many types
            return f"ERROR: {filename} could not be read as a Word file ({type(exc).__name__}: {exc})."
        return f"[{filename}: {total} paragraphs]\n\n{text}" if text.strip() else f"{filename} has no text in that range."
    try:
        text, total_pages = extract_pdf_text(destination, start_page, end_page)
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on malformed files
        return f"ERROR: {filename} could not be read as a PDF ({type(exc).__name__}: {exc})."
    if not text.strip():
        return (
            f"{filename} has {total_pages} pages but no extractable text in that range — it is "
            f"most likely scanned. Report that honestly; do not guess at the contents."
        )
    return f"[{filename}: {total_pages} pages]\n\n{text}"


_NGO_REFUSAL = ("REFUSED: researching an NGO is for its stewards and the Sangam team, and only an NGO "
                "Sangam already holds. Report what you found in your summary instead.")


async def _may_research(conn: Any, caller: Any, head: dict[str, Any], findings: list[dict], slug: str) -> bool:
    """Whether a non-staff caller stewards the NGO this save writes to; the brief is keyed on the slug alone."""
    row = {"slug": slug, "entity_kind": "org", "entity_name": head["entity_name"],
           "canonical_name": head["canonical_name"], "findings": findings}
    match = await org_match(conn, row)
    held = await (await conn.execute("SELECT id FROM orgs WHERE slug = %s", (slug,))).fetchall()
    ids = {r["id"] for r in held} | ({match.entity_id} if match and match.method in MERGEABLE else set())
    return bool(ids) and all(caller.can_research_org(i) for i in ids)


_NO_RUN = "{} failed: no research run is open. Report what you found in your summary instead."


@tool
async def record_findings(
    findings: list[dict[str, Any]] | dict[str, Any] | str | None = None,
    gaps: list[dict[str, Any]] | dict[str, Any] | str | None = None,
    unplaced: list[dict[str, Any]] | dict[str, Any] | str | None = None,
) -> str:
    """Record what you found, a few items at a time, as you go. Nothing recorded needs sending again.

    findings: one object per fact: `concept` plus that concept's keys from research_goals, and always
    `evidence` (the sentence that states it), `source_url`, `confidence`, and `page` for a PDF.
    gaps: {concept, fiscal_year, field, reason, detail} for each thing looked for and not got; reason is
    not_stated (read, does not say), blocked (could not be read) or not_reached (the run stopped first).
    unplaced: {field, value, evidence, source_url} for a stated fact no concept has a key for.

    Each item is checked on its own: valid ones are kept, the reply names only the refused ones, and a
    key that is not a field is dropped. Sending a fact again from that source replaces its earlier copy,
    and the reply names a replacement that changed its values.
    """
    try:
        current = draft.CURRENT.get()
        return draft.record(current, findings, gaps, unplaced) if current else _NO_RUN.format("record_findings")
    except Exception as exc:
        logger.exception("record_findings failed")
        return f"record_findings failed: {type(exc).__name__}. Record the items again."


def _json(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else json.loads(value or "[]")


def _fitting(gaps: list[dict[str, Any]], head: dict[str, Any]) -> list[dict[str, Any]]:
    """A gap the save's kind is not researched for is dropped, since record_findings cannot take one back."""
    if head["entity_kind"] == "unknown":
        return gaps
    allowed = set(concepts_for(head["entity_kind"]))
    return [g for g in gaps if g.get("concept") in allowed]


def _notes(prior: dict[str, Any] | None, stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A refresh's removals stay; an update's note stays while the row still holds a finding with its key."""
    keys = {fact_key(f) for f in stored}
    return [e for e in _json(prior and prior.get("supersedes"))
            if not e.get("updated") or tuple(e["key"]) in keys]


def _kept_label(head: dict[str, Any], prior: dict[str, Any], found: bool) -> dict[str, Any]:
    """A run that found nothing, or could not tell the kind, does not relabel what earlier today's run found."""
    if head["entity_kind"] == "unknown" and prior["entity_kind"] != "unknown":
        head = {**head, "entity_kind": prior["entity_kind"]}
    if found and head["status"] == "not_found":
        status = prior["status"] if prior["status"] not in ("not_found", "wrong_entity") else "partial"
        head = {**head, "status": status, "stopped_reason": head["stopped_reason"] or prior["stopped_reason"]
                or "This run found nothing more; the findings are from earlier today's research."}
    return head


def _merged(head: dict[str, Any], current: draft.Draft,
            prior: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """This run's draft over the row saved today, so a second save adds to the first and never shrinks it; and the
    refresh's carried findings, which were checked when first saved and are kept beside it unchecked."""
    if head["status"] == "wrong_entity":
        return {**head, "findings": current.findings, "gaps": _fitting(current.gaps, head),
                "unplaced": current.unplaced}, []
    if not prior or prior["status"] == "wrong_entity":
        # A wrong_entity row is another organisation: nothing of it is carried into the right one.
        return {**head, "findings": current.findings, "unplaced": current.unplaced,
                "gaps": _fitting(draft.merged_gaps([], current.gaps, current.findings), head)}, []
    before = _json(prior["findings"])
    findings = merge_findings([{"findings": before}, {"findings": current.findings}])
    kept = {fact_key(f) for f in findings}
    carried = [f for f in before if f.get(CARRIED) and fact_key(f) not in kept]
    head = _kept_label(head, prior, bool(findings))
    return {
        **head,
        "findings": findings,
        "gaps": _fitting(draft.merged_gaps(_json(prior["gaps"]), current.gaps, findings), head),
        "sources_read": list(dict.fromkeys([*(prior["sources_read"] or []), *head["sources_read"]])),
        "unplaced": current.unplaced,
    }, carried


@tool
async def save_research(
    entity_name: str,
    entity_kind: Literal["funder", "org", "unknown"],
    status: Literal["complete", "partial", "not_found", "wrong_entity"],
    summary: str,
    canonical_name: str | None = None,
    website: str | None = None,
    stopped_reason: str | None = None,
    goals: list[str] | None = None,
    years: list[str] | None = None,
    sources_read: list[str] | None = None,
) -> str:
    """Save everything record_findings recorded in this run. Call it LAST, before you report back.

    It takes no findings: those are already recorded. It merges them into anything saved for this
    organisation earlier today, checks every field has a finding or a gap, and names only what is missing;
    record those, then call this again.

    Args:
        entity_name: the name as it was asked for.
        entity_kind: 'funder' if it GIVES money, 'org' if it RECEIVES it, 'unknown' only when research
            did not get far enough to tell.
        status: 'complete' if you answered the questions; 'partial' with stopped_reason if the run ran out;
            'not_found' if the sources have nothing; 'wrong_entity' if what you found is another organisation.
        summary: a few sentences, factual, no judgement.
        canonical_name: as the strongest source writes it.
        website: the organisation's own site.
        stopped_reason: REQUIRED for 'partial' and 'wrong_entity': why research ended where it did.
        goals: what you set out to find, from research_goals, one line each.
        years: the fiscal years you were asked to cover, e.g. ['FY2024-25'].
        sources_read: every URL you read.
    """
    current = draft.CURRENT.get()
    if current is None:
        return _NO_RUN.format("save_research")
    head = {"entity_name": entity_name, "canonical_name": canonical_name, "entity_kind": entity_kind,
            "website": website, "status": status, "stopped_reason": stopped_reason, "summary": summary,
            "goals": goals or [], "years": years or [], "sources_read": sources_read or []}
    # A staff finding quotes a confidential cell; its failures carry the exception type only.
    staff_save = any(is_staff_source_url(f.get("source_url") or "") for f in current.findings)
    caller = scope()
    if entity_kind == "org" and not (caller.is_staff or caller.steward_of):
        return _NGO_REFUSAL
    # What the tools fetched in this researcher's run, not what the model says it read; None outside a run.
    collected = snapshots.COLLECTED.get()
    try:
        slug = slugify(canonical_name or entity_name)
        pool = get_pool()
        async with pool.connection() as conn:
            if entity_kind == "org" and not caller.is_staff and not await _may_research(
                    conn, caller, head, current.findings, slug):
                return _NGO_REFUSAL
            prior = await (
                await conn.execute(
                    "SELECT fact_count, status, entity_kind, stopped_reason, researched_by, findings, gaps, sources_read, "
                    "snapshot_ids, supersedes "
                    "FROM entity_research WHERE slug = %s AND researched_on = current_date",
                    (slug,),
                )
            ).fetchone()
        # One row per entity per day is shared, so only staff add to what someone else saved.
        if prior and not caller.is_staff and prior["researched_by"] != caller.user_id:
            return (f"REFUSED: {slug} was already researched and saved today. Report back with "
                    f"slug={slug!r} and saved=true, and say the research on file is today's.")
        if status == "wrong_entity" and prior and prior["status"] != "wrong_entity" and prior["fact_count"]:
            return (f"REFUSED, nothing saved: {slug} already holds {prior['fact_count']} findings on the right "
                    f"organisation today, which a wrong_entity save would erase. Report back status wrong_entity "
                    f"with saved=false.")
        replaced = ""
        if prior and "unknown" not in (prior["entity_kind"], entity_kind) and prior["entity_kind"] != entity_kind:
            if prior["fact_count"] and not current.findings:
                return (f"REFUSED, nothing saved: {slug} already holds {prior['fact_count']} findings saved today as "
                        f"a {prior['entity_kind']}, and this run recorded none to replace them. Report back with "
                        f"slug={slug!r} and saved=false, and say today's research on file is as a "
                        f"{prior['entity_kind']}.")
            # One slug is one organisation, researched as one kind: the other kind's findings would fail its checks.
            replaced = (f" It replaced the {prior['fact_count']} findings saved earlier today as a "
                        f"{prior['entity_kind']}; say so in your summary.")
            prior = None
        payload, carried = _merged(head, current, prior)
        staff_save = staff_save or any(is_staff_source_url(f.get("source_url") or "")
                                       for f in [*payload["findings"], *carried])
        try:
            findings = EntityResearch.model_validate(payload, context=STORED)
        except ValidationError as exc:
            current.refusals += 1
            refused = list(payload["findings"])  # drop_refused shrinks the draft, which this may be
            gone = draft.drop_refused(current, exc, refused, payload["entity_kind"])
            taken = (f"\nTaken out of this run: {', '.join(gone)}. Record each again with record_findings, fixed, "
                     "or leave it out." if gone else "")
            return ("REFUSED, nothing saved:\n" + "\n".join(f"- {p}" for p in draft.problems(exc, refused))
                    + taken + "\nFix this call's own arguments if a problem names them, then call save_research again.")
        # The expected way to finish the contract, so it is not a refusal that moves the run to the strong model.
        if missing := unanswered(findings):
            return (
                f"REFUSED, nothing saved: every field gets a finding or a gap, and {len(missing)} have neither: "
                f"{'; '.join(missing[:40])}. Record each with record_findings, as a finding or a gap "
                f"{{concept, field, fiscal_year, reason, detail}}: not_stated or blocked naming the source, or "
                f"not_reached naming what was left unread. Nothing already recorded needs sending again. "
                f"Then call save_research again."
            )
        prior_ids = (prior["snapshot_ids"] or []) if prior else []
        snapshot_ids = list(dict.fromkeys([*prior_ids, *collected])) if collected is not None else None
        stored = [f.model_dump(mode="json") for f in findings.findings] + carried
        async with pool.connection() as conn, conn.transaction():
            row = await (
                await conn.execute(
                    """
                    INSERT INTO entity_research (
                        entity_name, canonical_name, entity_kind, slug, website, status,
                        stopped_reason, summary, findings, not_found, sources_read, fact_count,
                        goals, schema_version, gaps, years, snapshot_ids, supersedes, researched_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                            %s::jsonb, %s, %s::jsonb, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (slug, researched_on) DO UPDATE SET
                        entity_name = EXCLUDED.entity_name,
                        canonical_name = EXCLUDED.canonical_name,
                        entity_kind = EXCLUDED.entity_kind,
                        website = EXCLUDED.website,
                        status = EXCLUDED.status,
                        stopped_reason = EXCLUDED.stopped_reason,
                        summary = EXCLUDED.summary,
                        findings = EXCLUDED.findings,
                        not_found = EXCLUDED.not_found,
                        sources_read = EXCLUDED.sources_read,
                        fact_count = EXCLUDED.fact_count,
                        goals = EXCLUDED.goals,
                        schema_version = EXCLUDED.schema_version,
                        gaps = EXCLUDED.gaps,
                        years = EXCLUDED.years,
                        snapshot_ids = EXCLUDED.snapshot_ids,
                        supersedes = EXCLUDED.supersedes,
                        researched_by = EXCLUDED.researched_by,
                        researched_at = now()
                    RETURNING *
                    """,
                    (
                        findings.entity_name, findings.canonical_name, findings.entity_kind, slug,
                        findings.website, findings.status, findings.stopped_reason,
                        findings.summary, json.dumps(stored),
                        findings.not_found, findings.sources_read, len(stored),
                        json.dumps(findings.goals), SCHEMA_VERSION,
                        json.dumps([g.model_dump(mode="json") for g in findings.gaps]), findings.years,
                        snapshot_ids, json.dumps(_notes(prior, stored)), caller.user_id,
                    ),
                )
            ).fetchone()
            history = await rows_for(conn, slug)
        current.saved = {
            "slug": slug, "entity_kind": findings.entity_kind, "status": findings.status,
            "fact_count": len(stored), "source_count": len({f["source_url"] for f in stored}),
            "concepts_found": findings.concepts_found(), "not_found": findings.not_found,
        }
        current.goals = findings.goals
        current.record = {"findings": stored, "gaps": [g.model_dump(mode="json") for g in findings.gaps]}
        unfetched = (await snapshots.log_unfetched(slug, snapshot_ids, [f["source_url"] for f in stored]) or []
                     if snapshot_ids is not None else [])
        # Publish the brief with the same call that saves it: waiting for a
        # person to run `make client-docs` left the funder page's link dead in
        # between. Silent on failure, like archiving — the model cannot act on
        # it and the findings are saved either way.
        try:
            unplaced = [] if findings.status == "wrong_entity" else [u.model_dump(mode="json") for u in findings.unplaced]
            published = await publish(history, unplaced)
        except Exception:  # noqa: BLE001 - the brief could not be read, so it is left as it was
            logger.warning("brief for %s not merged: Storage could not be read", slug)
            published = None

        found = ", ".join(findings.concepts_found()) or "nothing"
        merged = (f" Merged with the {prior['fact_count']} findings saved earlier today."
                  if prior and prior["status"] != "wrong_entity" and status != "wrong_entity" else "")
        # Only claim what happened. With Storage unconfigured the brief exists
        # nowhere until someone renders it on the host. "brief is published" is
        # matched by the Import UI's milestone strip — a test pins the phrase.
        where = (
            "The brief is published and the funder page links it. "
            if published
            else f"It appears in docs/entities/{slug}.md on the next `make client-docs`. "
        )
        quoted = quoted_only(findings)
        unextracted = (
            f" These numbers are only inside quotes: {' | '.join(quoted)}. If any is a reach figure, a "
            f"count of places or an amount, record it as a finding and save again."
            if quoted else ""
        )
        unread = (f" No tool read these cited pages in this run; check the findings citing them: "
                  f"{', '.join(unfetched[:10])}." if unfetched else "")
        return (
            f"Saved as entity_research #{row['id']} ({slug}): {len(stored)} findings "
            f"across {found}; status {findings.status}. Report back with slug={slug!r} and "
            f"saved=true. {where}"
            f"promote_research moves what has a writer into the catalog.{merged}{replaced}{unextracted}{unread}"
        )
    except Exception as exc:
        if staff_save:
            logger.warning("save_research failed for %s (%s)", entity_name, type(exc).__name__)
            return f"save_research failed: {type(exc).__name__}. Report the failure in your summary, without repeating any row."
        logger.exception("save_research failed for %s", entity_name)
        return f"save_research failed: {type(exc).__name__}: {exc}. Report your findings in text."


@tool
async def publish_brief(slug: str = "") -> str:
    """Re-publish a saved research brief, so the funder page serves the current one.

    `save_research` already does this for the entity it just saved, so reach for
    this only to republish: research saved before publishing existed, or a brief
    that needs regenerating after the renderer changed.

    Args:
        slug: one entity, or empty for every researched entity.
    """
    if refused := staff_only("publish_brief"):
        return refused
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM entity_research "
                    + ("WHERE slug = %s " if slug else "")
                    + "ORDER BY slug, researched_on, researched_at",
                    (slug,) if slug else (),
                )
            ).fetchall()
        if not rows:
            return f"No saved research{f' for {slug!r}' if slug else ''}. Research first."

        by_slug: dict[str, list[dict]] = {}
        for r in rows:
            by_slug.setdefault(r["slug"], []).append(dict(r))
        done = []
        for s, history in by_slug.items():
            try:
                if await publish(history):
                    done.append(s)
            except Exception:  # noqa: BLE001 - one unreadable brief is left as it was; the rest still publish
                logger.warning("brief for %s not merged: Storage could not be read", s)
        if not done:
            return (
                f"Published nothing of {len(by_slug)}. Storage is not configured, so a brief "
                f"exists only as docs/entities/<slug>.md after `make client-docs` on the host."
            )
        missed = [s for s in by_slug if s not in done]
        return (
            f"Published {len(done)} brief(s): {', '.join(done)}."
            + (f" Failed: {', '.join(missed)}." if missed else "")
        )
    except Exception as exc:
        logger.exception("publish_brief failed")
        return f"publish_brief failed: {type(exc).__name__}: {exc}"

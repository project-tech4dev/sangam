"""The research path: search, a page, a file, a PDF — each gated on access.

The pipeline adapters handle the two sources we enumerate. These are for the
research the hand-vetted sheets did by hand: open the funder's CSR report, read
the pages that carry the figures, quote the sentence. `save_research` ends the
path — it is the only tool here that writes, and it writes findings, not catalog
rows.
"""

from __future__ import annotations

import json
import logging

import httpx
import trafilatura
from langchain_core.tools import tool

from app.agent.tools.files import _safe_name, downloads_dir, extract_pdf_text
from app.agent.tools.web import make_web_search
from app.core.config import get_settings
from app.db.pool import get_pool
from app.ingest.access import check_url
from app.ingest.adapters._http import TIMEOUT_SECONDS, USER_AGENT
from app.ingest.brief import publish
from app.ingest.research_records import SCHEMA_VERSION, EntityResearch
from app.ingest.staff_sources import is_staff_source_url
from app.ingest.writer import slugify
from app.integrations import storage

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 8_000
MAX_DOWNLOAD_MB = 60
PDF_TEXT_CHARS = 12_000
PAGE_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Encoding": "gzip, deflate"}


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

    results = raw.get("results", []) if isinstance(raw, dict) else raw
    if not results:
        return f"No results for {query!r}. Try the funder's own domain, or different wording."
    lines = [f"{len(results)} results for {query!r}:"]
    for r in results[:max_results]:
        url = r.get("url", "")
        refusal = await check_url(url)
        mark = "READABLE" if refusal is None else "HELD"
        lines.append(f"\n[{mark}] {r.get('title', '(no title)')}\n  {url}")
        if refusal:
            lines.append(f"  why held: {refusal[:180]}")
    return "\n".join(lines)


@tool
async def read_page(url: str) -> str:
    """Read a web page as text, if Sangam is allowed to read it.

    Use this for a funder's CSR page, an about page, a press release — anything
    the checklist needs that is not already covered by a source adapter. The URL
    is checked against the source registry and the site's robots.txt BEFORE it is
    fetched: a refusal is a final answer, not an obstacle to route around. Quote
    the sentence you rely on; the importer verifies quotes against this text.
    """
    refusal = await check_url(url)
    if refusal:
        return f"REFUSED: {refusal}"
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=TIMEOUT_SECONDS, headers=PAGE_HEADERS
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return f"ERROR: {url} returned HTTP {exc.response.status_code}. Nothing was read."
    except httpx.HTTPError as exc:
        return f"ERROR: fetching {url} failed ({type(exc).__name__}: {exc})."

    if "pdf" in response.headers.get("content-type", "").lower() or url.lower().endswith(".pdf"):
        return (
            f"{url} is a PDF ({len(response.content):,} bytes). Use fetch_document to save it, "
            f"then read_document_pages to read it."
        )
    text = trafilatura.extract(response.text, url=url) or ""
    if not text.strip():
        return f"No readable text could be extracted from {url}."
    if len(text) > MAX_CONTENT_CHARS:
        return text[:MAX_CONTENT_CHARS] + f"\n\n[truncated at {MAX_CONTENT_CHARS} characters]"
    return text


@tool
async def fetch_document(url: str, filename: str | None = None) -> str:
    """Download a PDF or other document, if Sangam is allowed to read it.

    CSR impact reports, BRSR filings and annual reports are PDFs — this is how
    the figures in them are reached. Saves the file and returns its name; read it
    with read_document_pages. Access is checked before anything is fetched.
    """
    refusal = await check_url(url)
    if refusal:
        return f"REFUSED: {refusal}"
    limit = MAX_DOWNLOAD_MB * 1024 * 1024
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=120, headers=PAGE_HEADERS
        ) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            name = _safe_name(filename or url.split("?")[0].rstrip("/").rsplit("/", 1)[-1])
            destination = downloads_dir() / name
            size = 0
            # Blocking write of a bounded download, behind the run gate.
            # An async file layer would cost more than it saves here.
            with open(destination, "wb") as fh:  # noqa: ASYNC230
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        fh.close()
                        destination.unlink(missing_ok=True)
                        return f"ERROR: {url} is larger than the {MAX_DOWNLOAD_MB} MB limit."
                    fh.write(chunk)
            content_type = response.headers.get("content-type", "application/octet-stream")
    except httpx.HTTPError as exc:
        return f"ERROR: download of {url} failed ({type(exc).__name__}: {exc})."

    # Archive it, so a fact outlives its source URL. Silent either way: the
    # model cannot act on a storage failure, and downloads_dir is still where
    # read_document_pages looks. A file too large for the bucket is still read
    # here - refusing to read a 55 MB annual report because it cannot be
    # archived would break the job to protect the record of it.
    data = destination.read_bytes()
    await storage.upload(
        storage.SOURCE_ARCHIVE, storage.archive_key(url, data, name), data, content_type
    )
    return f"Saved {name} ({size:,} bytes). Read it with read_document_pages('{name}')."


@tool
def read_document_pages(filename: str, start_page: int = 1, end_page: int | None = None) -> str:
    """Read text from a downloaded PDF, a page range at a time.

    Pages are 1-indexed; omit end_page to read to the end. A long report is
    truncated — call again with a later start_page to continue. A scanned PDF has
    no text layer and returns nothing: say so rather than guessing at its contents.
    """
    destination = downloads_dir() / _safe_name(filename)
    if not destination.exists():
        available = ", ".join(sorted(p.name for p in downloads_dir().iterdir())) or "(none)"
        return f"ERROR: {filename} is not in the downloads folder. Available: {available}"
    try:
        text, total_pages = extract_pdf_text(destination, start_page, end_page)
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on malformed files
        return f"ERROR: {filename} could not be read as a PDF ({type(exc).__name__}: {exc})."
    if not text.strip():
        return (
            f"{filename} has {total_pages} pages but no extractable text in that range — it is "
            f"most likely scanned. Report that honestly; do not guess at the contents."
        )
    if len(text) > PDF_TEXT_CHARS:
        text = text[:PDF_TEXT_CHARS] + (
            f"\n\n[truncated — {total_pages} pages in total; call again with a later start_page]"
        )
    return f"[{filename}: {total_pages} pages]\n\n{text}"


STAFF_SUMMARY = "\n\nFrom the staff workbooks: "


def _origin(url: str | None) -> str:
    return "staff" if is_staff_source_url(url) else "web"


def _merge(prior: dict, incoming: dict, origins: set[str]) -> dict:
    """A save replaces only the stored findings of its own origin (web or staff) and keeps the rest."""
    if origins >= {"web", "staff"}:
        return incoming
    stored = prior["findings"] if isinstance(prior["findings"], list) else json.loads(prior["findings"] or "[]")
    kept = [f for f in stored if _origin(f["source_url"]) not in origins]
    findings = kept + incoming["findings"]
    web_text, _, staff_text = (prior["summary"] or "").partition(STAFF_SUMMARY)
    staff_only = origins == {"staff"}
    if staff_only:
        staff_text = incoming["summary"]
    else:
        web_text = incoming["summary"]
    summary = (web_text + STAFF_SUMMARY + staff_text) if web_text and staff_text else (
        web_text or STAFF_SUMMARY.lstrip() + staff_text)
    # The web researcher confirms the entity, so its identity and status govern once it has saved.
    lead, other = (prior, incoming) if staff_only and web_text else (incoming, prior)
    out = {k: lead[k] or other[k] for k in ("entity_name", "canonical_name", "website")}
    out["entity_kind"] = lead["entity_kind"] if lead["entity_kind"] != "unknown" else other["entity_kind"]
    out["status"], out["stopped_reason"] = lead["status"], lead["stopped_reason"]
    if out["status"] == "not_found" and findings:
        out["status"] = "partial"
        out["stopped_reason"] = out["stopped_reason"] or "only one source kind had findings"
    found = {f["concept"] for f in findings}
    prior_goals = prior["goals"] if isinstance(prior["goals"], list) else json.loads(prior["goals"] or "[]")
    sources = [u for u in prior["sources_read"] or [] if _origin(u) not in origins] + incoming["sources_read"]
    return {
        **out, "summary": summary, "findings": findings,
        "not_found": [c for c in dict.fromkeys([*(prior["not_found"] or []), *incoming["not_found"]])
                      if c not in found],
        "sources_read": list(dict.fromkeys(sources)),
        "goals": list(dict.fromkeys([*prior_goals, *incoming["goals"]])),
    }


@tool
async def save_research(findings: EntityResearch, replace: bool = False) -> str:
    """Save what you found. Call this LAST, once, before you report back.

    Research that is only spoken disappears when the conversation does. This is
    what makes it durable, and what the client and entity documents are rendered
    from. Every finding needs the sentence that states it and the URL it came
    from — the tool refuses anything else, so do not summarise the evidence away.

    Report `status` honestly: 'complete' only if you answered the questions,
    'partial' with a reason if the budget ran out, 'not_found' if the sources
    have nothing, 'wrong_entity' if what you found is a different organisation
    from the one asked about.

    Args:
        findings: everything you found, with the evidence for each fact.
        replace: set only when you mean to discard a fuller result saved for
            this organisation earlier today. Saving is an upsert keyed on
            (slug, date), so without this a short re-run can quietly overwrite
            a long one — which has happened, and cost fifteen findings.
    """
    # A staff finding quotes a confidential cell; its failures carry the exception type only.
    staff_save = any(is_staff_source_url(f.source_url) for f in findings.findings)
    try:
        slug = slugify(findings.canonical_name or findings.entity_name)
        incoming = {
            "entity_name": findings.entity_name, "canonical_name": findings.canonical_name,
            "entity_kind": findings.entity_kind, "website": findings.website, "status": findings.status,
            "stopped_reason": findings.stopped_reason, "summary": findings.summary,
            "findings": [f.model_dump(mode="json") for f in findings.findings],
            "not_found": list(findings.not_found), "sources_read": list(findings.sources_read),
            "goals": list(findings.goals),
        }
        origins = {_origin(f["source_url"]) for f in incoming["findings"]}
        origins |= {_origin(u) for u in incoming["sources_read"]}
        origins = origins or {"web"}
        pool = get_pool()
        async with pool.connection() as conn, conn.transaction():
            # A staff-reader and a researcher save the same slug at once; serialise them.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"entity_research:{slug}",))
            prior = await (
                await conn.execute(
                    "SELECT * FROM entity_research WHERE slug = %s AND researched_on = current_date",
                    (slug,),
                )
            ).fetchone()
            if origins == {"staff"} and not prior:
                return (
                    f"REFUSED: no research saved for {slug} today — the entity-researcher runs first. "
                    f"Save under the exact slug your task gives, as entity_name."
                )
            prior_same = [f for f in (prior or {}).get("findings") or [] if _origin(f["source_url"]) in origins]
            if prior and len(prior_same) > len(incoming["findings"]) and not replace:
                which = " and ".join(sorted(origins))
                return (
                    f"REFUSED: {slug} already has {len(prior_same)} {which} findings saved today and "
                    f"you are offering {len(incoming['findings'])}. Saving would replace the fuller "
                    f"result. If you meant to, call again with replace=true; otherwise report what "
                    f"you found and say the earlier research is already on file."
                )
            merged = _merge(dict(prior), incoming, origins) if prior else incoming
            row = await (
                await conn.execute(
                    """
                    INSERT INTO entity_research (
                        entity_name, canonical_name, entity_kind, slug, website, status,
                        stopped_reason, summary, findings, not_found, sources_read, fact_count,
                        goals, schema_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                            %s::jsonb, %s)
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
                        researched_at = now()
                    RETURNING *
                    """,
                    (
                        merged["entity_name"], merged["canonical_name"], merged["entity_kind"], slug,
                        merged["website"], merged["status"], merged["stopped_reason"], merged["summary"],
                        json.dumps(merged["findings"]), merged["not_found"], merged["sources_read"],
                        len(merged["findings"]), json.dumps(merged["goals"]), SCHEMA_VERSION,
                    ),
                )
            ).fetchone()
        # Publish the brief with the same call that saves it: waiting for a
        # person to run `make client-docs` left the funder page's link dead in
        # between. Silent on failure, like archiving — the model cannot act on
        # it and the findings are saved either way.
        published = await publish(dict(row))

        found = ", ".join(findings.concepts_found()) or "nothing"
        kept = len(merged["findings"]) - len(incoming["findings"])
        replaced = (
            f" Replaced {len(prior_same)} findings saved earlier today"
            + (f"; kept {kept} from the other source kind." if kept else ".")
            if prior else ""
        )
        # Only claim what happened. With Storage unconfigured the brief exists
        # nowhere until someone renders it on the host. "brief is published" is
        # matched by the Import UI's milestone strip — a test pins the phrase.
        where = (
            "The brief is published and the funder page links it. "
            if published
            else f"It appears in docs/entities/{slug}.md on the next `make client-docs`. "
        )
        return (
            f"Saved as entity_research #{row['id']} ({slug}): {len(findings.findings)} findings "
            f"across {found} ({row['fact_count']} on the row); status {row['status']}. Report back with slug={slug!r} and "
            f"saved=true. {where}"
            f"promote_research moves what has a writer into the catalog.{replaced}"
        )
    except Exception as exc:
        if staff_save:
            logger.warning("save_research failed for %s (%s)", findings.entity_name, type(exc).__name__)
            return f"save_research failed: {type(exc).__name__}. Report the failure in your summary, without repeating any row."
        logger.exception("save_research failed for %s", findings.entity_name)
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
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT DISTINCT ON (slug) * FROM entity_research "
                    + ("WHERE slug = %s " if slug else "")
                    + "ORDER BY slug, researched_at DESC",
                    (slug,) if slug else (),
                )
            ).fetchall()
        if not rows:
            return f"No saved research{f' for {slug!r}' if slug else ''}. Research first."

        done = [r["slug"] for r in rows if await publish(dict(r))]
        if not done:
            return (
                f"Published nothing of {len(rows)}. Storage is not configured, so a brief "
                f"exists only as docs/entities/<slug>.md after `make client-docs` on the host."
            )
        missed = [r["slug"] for r in rows if r["slug"] not in done]
        return (
            f"Published {len(done)} brief(s): {', '.join(done)}."
            + (f" Failed: {', '.join(missed)}." if missed else "")
        )
    except Exception as exc:
        logger.exception("publish_brief failed")
        return f"publish_brief failed: {type(exc).__name__}: {exc}"

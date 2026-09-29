"""Reading tools for the importer: a page, a file, a PDF — each gated on access.

The pipeline adapters handle the two sources we enumerate. These are for the
research the hand-vetted sheets did by hand: open the funder's CSR report, read
the pages that carry the figures, quote the sentence.
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
from app.ingest.research_records import EntityResearch
from app.ingest.writer import slugify

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
    except httpx.HTTPError as exc:
        return f"ERROR: download of {url} failed ({type(exc).__name__}: {exc})."
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


@tool
async def save_research(findings: EntityResearch) -> str:
    """Save what you found. Call this LAST, once, before you report back.

    Research that is only spoken disappears when the conversation does. This is
    what makes it durable, and what the client and entity documents are rendered
    from. Every finding needs the sentence that states it and the URL it came
    from — the tool refuses anything else, so do not summarise the evidence away.

    Report `status` honestly: 'complete' only if you answered the questions,
    'partial' with a reason if the budget ran out, 'not_found' if the sources
    have nothing, 'wrong_entity' if what you found is a different organisation
    from the one asked about.
    """
    try:
        slug = slugify(findings.canonical_name or findings.entity_name)
        pool = get_pool()
        async with pool.connection() as conn, conn.transaction():
            row = await (
                await conn.execute(
                    """
                    INSERT INTO entity_research (
                        entity_name, canonical_name, entity_kind, slug, website, status,
                        stopped_reason, summary, findings, not_found, sources_read, fact_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
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
                        researched_at = now()
                    RETURNING id
                    """,
                    (
                        findings.entity_name, findings.canonical_name, findings.entity_kind, slug,
                        findings.website, findings.status, findings.stopped_reason,
                        findings.summary,
                        json.dumps([f.model_dump(mode="json") for f in findings.findings]),
                        findings.not_found, findings.sources_read, len(findings.findings),
                    ),
                )
            ).fetchone()
        return (
            f"Saved as entity_research #{row['id']} ({slug}): {len(findings.findings)} findings, "
            f"status {findings.status}. It will appear in docs/entities/{slug}.md on the next "
            f"`make client-docs`."
        )
    except Exception as exc:
        logger.exception("save_research failed for %s", findings.entity_name)
        return f"save_research failed: {type(exc).__name__}: {exc}. Report your findings in text."

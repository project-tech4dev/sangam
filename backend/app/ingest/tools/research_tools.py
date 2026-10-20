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
from typing import Any

import httpx
import trafilatura
from langchain_core.tools import tool

from app.agent.tools.files import _safe_name, downloads_dir, extract_pdf_text
from app.agent.tools.web import make_web_search
from app.core.config import get_settings
from app.core.egress import TRUST
from app.db.pool import get_pool
from app.ingest.access import canonical_url, check_url, source_banner
from app.ingest.adapters._http import TIMEOUT_SECONDS, USER_AGENT
from app.ingest.brief import publish, rows_for
from app.ingest.caller import scope, staff_only
from app.ingest.contract import quoted_only, unanswered
from app.ingest.research_records import SCHEMA_VERSION, EntityResearch
from app.ingest.sources import rule_for_url
from app.ingest.staff_sources import is_staff_source_url
from app.ingest.writer import slugify
from app.integrations import storage

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_MB = 60
PAGE_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Encoding": "gzip, deflate"}


class _Stop(Exception):
    """Raised from the request hook: a redirect led somewhere this tool may not go."""

    def __init__(self, reply: str):
        super().__init__(reply)
        self.reply = reply


def _client(original: str, **kwargs: Any) -> httpx.AsyncClient:
    """A client that runs check_url on every hop BEFORE it is requested; httpx calls request hooks per redirect.
    A read that starts on a path-scoped source must stay on that source's allowed paths."""
    start = rule_for_url(original)
    scoped = start[1] if start and start[1].path_scoped else None

    async def guard(request: httpx.Request) -> None:
        target = str(request.url)
        if target == canonical_url(original):
            return  # the caller checked this exact URL already; both sides are httpx's form
        here = rule_for_url(target)
        if scoped is not None and (here is None or here[1].key != scoped.key):
            raise _Stop(f"REFUSED: {original} led to {target}, which is off {scoped.name}'s allowed paths "
                        f"and was not requested. Report this; do not follow it another way.")
        refusal = await check_url(target)
        if refusal:
            raise _Stop(f"REFUSED: {original} led to {target}, which was not requested. {refusal}")

    return httpx.AsyncClient(follow_redirects=True, event_hooks={"request": [guard]}, verify=TRUST, **kwargs)


def _compact_json(text: str) -> str:
    """A GitHub directory listing as one line per entry; any other JSON as it came."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, list) and data and all(isinstance(e, dict) and "name" in e and "type" in e for e in data):
        return "\n".join(f"{e['name']} · {e['type']} · {e.get('download_url') or e.get('path', '')}" for e in data)
    return text


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
        for r in results[:max_results]:
            url = r.get("url", "")
            refusal = await check_url(url)
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
        return await _read_page(url)
    except Exception as exc:  # noqa: BLE001 - errors are return values
        return f"read_page failed: {type(exc).__name__}: {exc}"


async def _read_page(url: str) -> str:
    url = canonical_url(url)
    refusal = await check_url(url)
    if refusal:
        return f"REFUSED: {refusal}"
    try:
        async with _client(url, timeout=TIMEOUT_SECONDS, headers=PAGE_HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()
    except _Stop as stop:
        return stop.reply
    except httpx.HTTPStatusError as exc:
        return f"ERROR: {url} returned HTTP {exc.response.status_code}. Nothing was read."
    except httpx.HTTPError as exc:
        return f"ERROR: fetching {url} failed ({type(exc).__name__}: {exc})."

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return (
            f"{url} is a PDF ({len(response.content):,} bytes). Use fetch_document to save it, "
            f"then read_document_pages to read it."
        )
    # trafilatura finds nothing in JSON (GuideStar's search, GitHub listings) or raw markdown (a dossier).
    if "json" in content_type:
        text = _compact_json(response.text)
    elif content_type.startswith("text/plain") or "markdown" in content_type:
        text = response.text
    else:
        text = trafilatura.extract(response.text, url=url) or ""
    if not text.strip():
        return f"No readable text could be extracted from {url}."
    # Kept as read, so a fact outlives a page that changes; silent like fetch_document's archive.
    data = text.encode()
    await storage.upload(storage.SOURCE_ARCHIVE, storage.archive_key(url, data, page_name(url)), data,
                         "text/markdown; charset=utf-8")
    # Uncut: a long page is evicted to a file the researcher pages back with read_file.
    return source_banner(str(response.url)) + text


def page_name(url: str) -> str:
    """A readable file name for an archived page: axisbankfoundation.org-what-we-do.md."""
    rest = url.split("://", 1)[-1].split("?")[0].split("#")[0].strip("/")
    host, _, path = rest.partition("/")
    stem = "-".join(p for p in [host.removeprefix("www."), *path.split("/")] if p)
    return _safe_name(stem.removesuffix(".html").removesuffix(".htm"))[:100] + ".md"


@tool
async def fetch_document(url: str, filename: str | None = None) -> str:
    """Download a PDF or other document, if Sangam is allowed to read it.

    CSR impact reports, BRSR filings and annual reports are PDFs — this is how
    the figures in them are reached. Saves the file and returns its name; read it
    with read_document_pages. Access is checked before anything is fetched.
    """
    try:
        return await _fetch_document(url, filename)
    except Exception as exc:  # noqa: BLE001 - errors are return values
        return f"fetch_document failed: {type(exc).__name__}: {exc}"


async def _fetch_document(url: str, filename: str | None) -> str:
    url = canonical_url(url)
    refusal = await check_url(url)
    if refusal:
        return f"REFUSED: {refusal}"
    limit = MAX_DOWNLOAD_MB * 1024 * 1024
    try:
        async with _client(url, timeout=120, headers=PAGE_HEADERS) as client, \
                client.stream("GET", url) as response:
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
    except _Stop as stop:
        return stop.reply
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

    Pages are 1-indexed; omit end_page to read to the end. A long result is saved
    to a file you page through with read_file. A scanned PDF has
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
    return f"[{filename}: {total_pages} pages]\n\n{text}"


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
    caller = scope()
    if findings.entity_kind == "org" and not (caller.is_staff or caller.steward_of):
        return ("REFUSED: researching an NGO is for its stewards and the Sangam team. Report what you "
                "found in your summary instead.")
    if missing := unanswered(findings):
        return (
            f"REFUSED: a save answers every field with a finding or a gap, and {len(missing)} have "
            f"neither: {'; '.join(missing[:40])}. For each, add the finding, or a gap "
            f"{{concept, field, fiscal_year, reason, detail}}: not_stated or blocked naming the source, or "
            f"not_reached naming what was left unread when the run stopped. Then save again."
        )
    try:
        slug = slugify(findings.canonical_name or findings.entity_name)
        pool = get_pool()
        async with pool.connection() as conn:
            prior = await (
                await conn.execute(
                    "SELECT fact_count, researched_by FROM entity_research "
                    "WHERE slug = %s AND researched_on = current_date",
                    (slug,),
                )
            ).fetchone()
        # One row per entity per day is shared, so only staff replace what someone else saved.
        if prior and not caller.is_staff and prior["researched_by"] != caller.user_id:
            return (f"REFUSED: {slug} was already researched and saved today. Report back with "
                    f"slug={slug!r} and saved=true, and say the research on file is today's.")
        if prior and prior["fact_count"] > len(findings.findings) and not replace:
            return (
                f"REFUSED: {slug} already has {prior['fact_count']} findings saved today and "
                f"you are offering {len(findings.findings)}. Saving would replace the fuller "
                f"result. If you meant to, call again with replace=true; otherwise report what "
                f"you found and say the earlier research is already on file."
            )
        async with pool.connection() as conn, conn.transaction():
            row = await (
                await conn.execute(
                    """
                    INSERT INTO entity_research (
                        entity_name, canonical_name, entity_kind, slug, website, status,
                        stopped_reason, summary, findings, not_found, sources_read, fact_count,
                        goals, schema_version, gaps, years, researched_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                            %s::jsonb, %s, %s::jsonb, %s, %s)
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
                        researched_by = EXCLUDED.researched_by,
                        researched_at = now()
                    RETURNING *
                    """,
                    (
                        findings.entity_name, findings.canonical_name, findings.entity_kind, slug,
                        findings.website, findings.status, findings.stopped_reason,
                        findings.summary,
                        json.dumps([f.model_dump(mode="json") for f in findings.findings]),
                        findings.not_found, findings.sources_read, len(findings.findings),
                        json.dumps(findings.goals), SCHEMA_VERSION,
                        json.dumps([g.model_dump(mode="json") for g in findings.gaps]), findings.years,
                        caller.user_id,
                    ),
                )
            ).fetchone()
            history = await rows_for(conn, slug)
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
        replaced = (
            f" Replaced {prior['fact_count']} findings saved earlier today."
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
        quoted = quoted_only(findings)
        unextracted = (
            f" These numbers are only inside quotes: {' | '.join(quoted)}. If any is a reach figure, a "
            f"count of places or an amount, add it as a finding and save again."
            if quoted else ""
        )
        return (
            f"Saved as entity_research #{row['id']} ({slug}): {len(findings.findings)} findings "
            f"across {found}; status {findings.status}. Report back with slug={slug!r} and "
            f"saved=true. {where}"
            f"promote_research moves what has a writer into the catalog.{replaced}{unextracted}"
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

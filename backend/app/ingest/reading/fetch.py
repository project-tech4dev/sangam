"""Fetch and clean a page or document, the one way both the researcher and the change check do it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import trafilatura

from app.core.config import get_settings
from app.core.egress import TRUST
from app.ingest.adapters._http import TIMEOUT_SECONDS, USER_AGENT
from app.ingest.reading.access import canonical_url, check_url, source_banner
from app.ingest.reading.registry import rule_for_url
from app.integrations import storage
from app.integrations.storage import _safe_name


def downloads_dir() -> Path:
    directory = Path(get_settings().downloads_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


MAX_DOWNLOAD_MB = 60
WORD = "wordprocessingml"  # in a .docx's content type
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


async def read_page_text(url: str) -> str:
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
    if kind := _document_kind(content_type, url):
        return (
            f"{url} is a {kind} ({len(response.content):,} bytes). Use fetch_document to save it, "
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


def _document_kind(content_type: str, url: str) -> str | None:
    path = url.lower().split("?")[0]
    if "pdf" in content_type or path.endswith(".pdf"):
        return "PDF"
    if WORD in content_type or path.endswith(".docx"):
        return "Word file"
    return None


def page_name(url: str) -> str:
    """A readable file name for an archived page: axisbankfoundation.org-what-we-do.md."""
    rest = url.split("://", 1)[-1].split("?")[0].split("#")[0].strip("/")
    host, _, path = rest.partition("/")
    stem = "-".join(p for p in [host.removeprefix("www."), *path.split("/")] if p)
    return _safe_name(stem.removesuffix(".html").removesuffix(".htm"))[:100] + ".md"


async def fetch_document_file(url: str, filename: str | None) -> str:
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
        # A Word file served from a link without its extension is still paged by paragraph.
        if WORD in content_type.lower() and not name.lower().endswith(".docx"):
            destination = destination.rename(destination.with_name(f"{name}.docx"))
            name = destination.name
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

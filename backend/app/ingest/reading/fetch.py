"""Fetch and clean a page or document, the one way both the researcher and the change check do it."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
import trafilatura
from pypdf import PdfReader

from app.core.config import get_settings
from app.core.egress import TRUST
from app.core.extract import extract_pdf_text
from app.ingest.adapters._http import TIMEOUT_SECONDS, USER_AGENT
from app.ingest.reading.access import canonical_url, check_url, source_banner
from app.ingest.reading.fingerprint import bytes_hash, text_hash
from app.ingest.reading.registry import rule_for_url
from app.ingest.reading.snapshots import known_fingerprint, remember
from app.integrations import storage
from app.integrations.storage import safe_name


def downloads_dir() -> Path:
    directory = Path(get_settings().downloads_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


MAX_DOWNLOAD_MB = 60
# A longer PDF is fingerprinted by its bytes: parsing all of a 400-page report held the tool's reply for minutes.
MAX_HASHED_PAGES = 100
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


@dataclass(frozen=True)
class Fetched:
    """One fetch, before anything is archived: the text or file, or why there is none."""

    url: str
    final_url: str | None = None
    status: int | None = None
    content_type: str = ""
    text: str = ""
    document: str | None = None  # "PDF" or "Word file" when a page URL served a file
    path: Path | None = None  # where a downloaded document was saved
    size: int = 0
    refused: str | None = None  # the whole REFUSED message
    error: str | None = None  # "<ExceptionType>: <message>" when no usable answer came back
    too_large: bool = False


async def fetch_page(url: str) -> Fetched:
    """Fetch and clean a page with the same access checks as research, and write nothing."""
    url = canonical_url(url)
    refusal = await check_url(url)
    if refusal:
        return Fetched(url, refused=f"REFUSED: {refusal}")
    try:
        async with _client(url, timeout=TIMEOUT_SECONDS, headers=PAGE_HEADERS) as client:
            response = await client.get(url)
    except _Stop as stop:
        return Fetched(url, refused=stop.reply)
    except httpx.HTTPError as exc:
        return Fetched(url, error=f"{type(exc).__name__}: {exc}")
    content_type = response.headers.get("content-type", "").lower()
    seen = Fetched(url, final_url=str(response.url), status=response.status_code, content_type=content_type,
                   size=len(response.content))
    if not response.is_success:
        return seen
    if kind := document_kind(content_type, url):
        return replace(seen, document=kind)
    # trafilatura finds nothing in JSON (GuideStar's search, GitHub listings) or raw markdown (a dossier).
    if "json" in content_type:
        text = _compact_json(response.text)
    elif content_type.startswith("text/plain") or "markdown" in content_type:
        text = response.text
    else:
        text = trafilatura.extract(response.text, url=url) or ""
    return replace(seen, text=text)


async def read_page_text(url: str) -> str:
    page = await fetch_page(url)
    url = page.url
    if page.refused:
        return page.refused
    if page.error:
        return f"ERROR: fetching {url} failed ({page.error})."
    if page.status is not None and not 200 <= page.status < 300:
        return f"ERROR: {url} returned HTTP {page.status}. Nothing was read."
    if page.document:
        return (
            f"{url} is a {page.document} ({page.size:,} bytes). Use fetch_document to save it, "
            f"then read_document_pages to read it."
        )
    text = page.text
    if not text.strip():
        return f"No readable text could be extracted from {url}."
    # Kept as read, so a fact outlives a page that changes; silent like fetch_document's archive.
    data = text.encode()
    key = await storage.upload(storage.SOURCE_ARCHIVE, storage.archive_key(url, data, page_name(url)), data,
                               "text/markdown; charset=utf-8")
    await remember(url, "page", text_hash(text), key)
    # Uncut: a long page is evicted to a file the researcher pages back with read_file.
    return source_banner(page.final_url or url) + text


def document_kind(content_type: str, url: str) -> str | None:
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
    return safe_name(stem.removesuffix(".html").removesuffix(".htm"))[:100] + ".md"


async def download(url: str, filename: str | None, directory: Path | None = None) -> Fetched:
    """Download a document with the same access checks as research, and archive nothing."""
    url = canonical_url(url)
    refusal = await check_url(url)
    if refusal:
        return Fetched(url, refused=f"REFUSED: {refusal}")
    limit = MAX_DOWNLOAD_MB * 1024 * 1024
    try:
        async with _client(url, timeout=120, headers=PAGE_HEADERS) as client, \
                client.stream("GET", url) as response:
            response.raise_for_status()
            name = safe_name(filename or url.split("?")[0].rstrip("/").rsplit("/", 1)[-1])
            destination = (directory or downloads_dir()) / name
            size = 0
            # Blocking write of a bounded download, behind the run gate.
            # An async file layer would cost more than it saves here.
            with open(destination, "wb") as fh:  # noqa: ASYNC230
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        fh.close()
                        destination.unlink(missing_ok=True)
                        return Fetched(url, status=response.status_code, too_large=True)
                    fh.write(chunk)
            content_type = response.headers.get("content-type", "application/octet-stream")
            final_url = str(response.url)
        # A Word file served from a link without its extension is still paged by paragraph.
        if WORD in content_type.lower() and not name.lower().endswith(".docx"):
            destination = destination.rename(destination.with_name(f"{name}.docx"))
    except _Stop as stop:
        return Fetched(url, refused=stop.reply)
    except httpx.HTTPStatusError as exc:
        return Fetched(url, status=exc.response.status_code, error=f"{type(exc).__name__}: {exc}")
    except httpx.HTTPError as exc:
        return Fetched(url, error=f"{type(exc).__name__}: {exc}")
    return Fetched(url, final_url=final_url, status=200, content_type=content_type, path=destination, size=size)


async def fetch_document_file(url: str, filename: str | None) -> str:
    got = await download(url, filename)
    url = got.url
    if got.refused:
        return got.refused
    if got.too_large:
        return f"ERROR: {url} is larger than the {MAX_DOWNLOAD_MB} MB limit."
    if got.error or got.path is None:
        return f"ERROR: download of {url} failed ({got.error})."
    destination, name = got.path, got.path.name
    # Archive it, so a fact outlives its source URL. Silent either way: the
    # model cannot act on a storage failure, and downloads_dir is still where
    # read_document_pages looks. A file too large for the bucket is still read
    # here - refusing to read a 55 MB annual report because it cannot be
    # archived would break the job to protect the record of it.
    data = destination.read_bytes()
    key = await storage.upload(
        storage.SOURCE_ARCHIVE, storage.archive_key(url, data, name), data, got.content_type
    )
    if key:
        # The key names the bytes, so an unchanged re-fetch reuses the hash rather than parsing the PDF again.
        fingerprint = await known_fingerprint(key) or await asyncio.to_thread(document_hash, destination)
        await remember(url, "document", fingerprint, key)
    return f"Saved {name} ({got.size:,} bytes). Read it with read_document_pages('{name}')."


def document_text(path: Path) -> str:
    """A PDF's whole text; empty for a scan, a damaged PDF, or any other file."""
    if not _is_pdf(path):
        return ""
    try:
        text, _ = extract_pdf_text(path, max_chars=None)  # every page: a change on page 80 is a change
    except Exception:  # noqa: BLE001 - pypdf raises far more than PyPdfError, and the read must not fail
        return ""
    return text if text.strip() else ""


def _is_pdf(path: Path) -> bool:
    """By its first bytes, not its name: a PDF from /download?id=42 is saved without .pdf."""
    with open(path, "rb") as fh:
        return b"%PDF-" in fh.read(1024)


def document_hash(path: Path, text: str | None = None) -> str:
    """A PDF by its text, so a re-export with new dates is not a change; a scan, a PDF over MAX_HASHED_PAGES
    or any other file by its bytes. Pass `text` when document_text already read it."""
    if _page_count(path) > MAX_HASHED_PAGES:
        return bytes_hash(path.read_bytes())
    text = document_text(path) if text is None else text
    return text_hash(text) if text else bytes_hash(path.read_bytes())


def _page_count(path: Path) -> int:
    """Without reading any page's text: pypdf holds the GIL, so a long report is not parsed to fingerprint it."""
    if not _is_pdf(path):
        return 0
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 - a damaged PDF is hashed by its bytes anyway
        return 0

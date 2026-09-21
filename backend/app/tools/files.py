"""File tools: download files to a local folder and extract text from PDFs."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
from langchain_core.tools import tool
from pypdf import PdfReader

from app.config import get_settings

MAX_DOWNLOAD_MB = 100
MAX_DOWNLOAD_BYTES = MAX_DOWNLOAD_MB * 1024 * 1024
PDF_TEXT_CHARS = 12_000
DOWNLOAD_TIMEOUT_SECONDS = 60
USER_AGENT = "Mozilla/5.0 (compatible; DeepAgentApp/0.1)"


def downloads_dir() -> Path:
    directory = Path(get_settings().downloads_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _safe_name(name: str) -> str:
    # Strip any directory components and shell-unfriendly characters so the
    # agent can never write outside the downloads folder.
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name[:120] or "download"


def _normalize_line(line: str) -> str:
    # Design-heavy PDFs often store text letter-spaced ("A N N U A L  R E P O R T").
    # Detect lines that are mostly single-character tokens and collapse them:
    # runs of 2+ spaces separate words, single spaces separate letters.
    tokens = line.split(" ")
    if len(tokens) > 4 and sum(len(t) == 1 for t in tokens) / len(tokens) > 0.6:
        words = re.split(r"\s{2,}", line.strip())
        return " ".join(word.replace(" ", "") for word in words)
    return line


def extract_pdf_text(source: Path, start_page: int = 1, end_page: int | None = None) -> tuple[str, int]:
    """Return (extracted_text, total_pages) for a PDF file. Text may be empty
    if the PDF has no embedded text layer (scanned/image-only documents)."""
    reader = PdfReader(str(source))
    total = len(reader.pages)
    start = max(start_page, 1)
    end = min(end_page or total, total)
    parts: list[str] = []
    for index in range(start - 1, end):
        page_text = (reader.pages[index].extract_text() or "").strip()
        if page_text:
            page_text = "\n".join(_normalize_line(l) for l in page_text.splitlines())
            parts.append(f"--- page {index + 1} ---\n{page_text}")
        if sum(len(p) for p in parts) > PDF_TEXT_CHARS * 2:
            break
    return "\n\n".join(parts), total


@tool
async def download_file(url: str, filename: str | None = None) -> str:
    """Download a file from a URL (PDF, CSV, image, report, etc.) and save it to
    the local downloads folder.

    Use this for documents and binary files that fetch_url cannot read, or when
    the user asks to save something locally. Returns the saved path. For PDFs,
    call read_pdf with the saved filename afterwards to extract the text.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                default_name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
                name = _safe_name(filename or default_name)
                destination = downloads_dir() / name
                size = 0
                with open(destination, "wb") as fh:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            fh.close()
                            destination.unlink(missing_ok=True)
                            return f"ERROR: {url} exceeds the {MAX_DOWNLOAD_MB} MB download limit."
                        fh.write(chunk)
                content_type = response.headers.get("content-type", "unknown")
    except httpx.HTTPError as exc:
        return f"ERROR: download of {url} failed ({type(exc).__name__}: {exc}). Try a different URL."

    hint = f" Use read_pdf('{name}') to extract its text." if name.lower().endswith(".pdf") else ""
    return f"Saved to {destination} ({size:,} bytes, {content_type}).{hint}"


@tool
def read_pdf(filename: str, start_page: int = 1, end_page: int | None = None) -> str:
    """Extract text from a PDF in the downloads folder (save it first with
    download_file).

    Pages are 1-indexed; omit end_page to read to the end. Long PDFs are
    truncated — call again with a page range to read further. Scanned or
    image-only PDFs have no text layer and will return nothing extractable.
    """
    destination = downloads_dir() / _safe_name(filename)
    if not destination.exists():
        available = ", ".join(sorted(p.name for p in downloads_dir().iterdir())) or "(none)"
        return f"ERROR: {filename} not found in the downloads folder. Available files: {available}"
    try:
        text, total_pages = extract_pdf_text(destination, start_page, end_page)
    except Exception as exc:  # pypdf raises many exception types on malformed files
        return f"ERROR: could not read {filename} as a PDF ({type(exc).__name__}: {exc})."

    if not text.strip():
        return (
            f"{filename} has {total_pages} pages but no extractable text layer in the "
            f"requested range — it is likely a scanned or image-based PDF. Text "
            f"extraction would require OCR, which is not available. Report this "
            f"honestly rather than guessing at the contents."
        )
    if len(text) > PDF_TEXT_CHARS:
        text = text[:PDF_TEXT_CHARS] + (
            f"\n\n[truncated — {total_pages} pages total; call read_pdf again with a "
            f"start_page/end_page range to continue reading]"
        )
    return f"[{filename}: {total_pages} pages]\n\n{text}"

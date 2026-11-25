"""Fetch today's version of each baseline source, and sort a failed fetch from a real answer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from app.ingest.reading.fetch import Fetched, document_hash, document_text, download, fetch_page
from app.ingest.reading.fingerprint import text_hash
from app.ingest.refresh.baseline import Baseline

OK, UNVERIFIED, DEAD = "ok", "unverified", "dead"
GONE = (404, 410)
# A few at once: far quicker than one by one, and still no burst for a funder's site.
FETCH_AT_ONCE = 3


@dataclass(frozen=True)
class Today:
    url: str
    status: str
    reason: str
    text: str = ""  # a page's cleaned text, or a PDF's extracted text
    path: Path | None = None  # a downloaded document; gone once the check's scratch folder is
    fingerprint: str | None = None  # hashed the way the tools hash it, so it compares with the baseline


async def fetch_today(source: Baseline, scratch: Path) -> Today:
    """Today's text for one source; a document is downloaded into scratch, never the researchers' folder."""
    if source.kind == "document":
        got = await download(source.url, None, scratch)
        text = await asyncio.to_thread(document_text, got.path) if got.path else ""
        today = classify(got, text)
        if today.status != OK or today.path is None:
            return today
        # The tools' own rule, page cap included, or a long report would never match its baseline.
        return replace(today, fingerprint=document_hash(today.path, text))
    got = await fetch_page(source.url)
    today = classify(got, got.text)
    return replace(today, fingerprint=text_hash(today.text)) if today.status == OK else today


async def fetch_all(sources: list[Baseline], scratch: Path) -> list[Today]:
    """In the baselines' order; each source gets its own folder, so two annual-report.pdf never collide."""
    gate = asyncio.Semaphore(FETCH_AT_ONCE)

    async def one(index: int, source: Baseline) -> Today:
        folder = scratch / str(index)
        folder.mkdir()
        async with gate:
            return await fetch_today(source, folder)

    return list(await asyncio.gather(*(one(i, s) for i, s in enumerate(sources))))


def classify(got: Fetched, text: str) -> Today:
    """A failure is unverified, never a change; only a 404, a 410 or a fall back to the home page is dead."""
    url = got.url
    if got.refused:
        return Today(url, UNVERIFIED, got.refused)
    if got.status in GONE:
        return Today(url, DEAD, f"HTTP {got.status}")
    if got.too_large:
        return Today(url, UNVERIFIED, "larger than the download limit")
    if got.error:
        return Today(url, UNVERIFIED, got.error)
    if got.status is not None and not 200 <= got.status < 300:
        return Today(url, UNVERIFIED, f"HTTP {got.status}")
    if _sent_home(url, got.final_url):
        return Today(url, DEAD, f"redirected to the home page {got.final_url}")
    if got.document:
        return Today(url, UNVERIFIED, f"now serves a {got.document}, not a page")
    if got.path is not None and "html" in got.content_type.lower():
        return Today(url, UNVERIFIED, "now serves a web page, not a document")
    if not text.strip() and got.path is None:
        return Today(url, UNVERIFIED, "no readable text")
    return Today(url, OK, f"HTTP {got.status}", text=text, path=got.path)


def _sent_home(url: str, final_url: str | None) -> bool:
    """A page that redirects to its site's root is a soft 404: the page is gone, the site isn't."""
    if not final_url:
        return False
    asked, landed = urlsplit(url), urlsplit(final_url)
    return asked.path.strip("/") != "" and landed.path.strip("/") == "" and not landed.query


def describe(slug: str, today: list[Today]) -> str:
    counts = {s: sum(t.status == s for t in today) for s in (OK, UNVERIFIED, DEAD)}
    head = f"{slug}: fetched {len(today)} · {counts[OK]} ok · {counts[UNVERIFIED]} unverified · {counts[DEAD]} dead"
    lines = [head]
    lines += [f"  {t.status:10}  {t.url}" + ("" if t.status == OK else f"  ({t.reason[:160]})") for t in today]
    return "\n".join(lines)

"""What text changed between a source's baseline and today, paragraph by paragraph."""

from __future__ import annotations

import asyncio
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path

from app.ingest.reading.fetch import document_text
from app.ingest.reading.fingerprint import normalise
from app.ingest.refresh.baseline import Baseline
from app.ingest.refresh.compare import CHANGED, DIFFERS, MINOR, Check, counts
from app.integrations import storage

SHOWN = 8  # paragraphs printed per side; the rest are counted


def paragraphs(text: str) -> list[str]:
    return [p for p in (normalise(line) for line in text.splitlines()) if p]


def diff(old: str, new: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Paragraphs removed and added, in page order; a paragraph that only moved is neither."""
    before, after = paragraphs(old), paragraphs(new)
    gone, came = Counter(before) - Counter(after), Counter(after) - Counter(before)
    return _take(before, gone), _take(after, came)


def _take(order: list[str], wanted: Counter[str]) -> tuple[str, ...]:
    left = Counter(wanted)
    picked = []
    for p in order:
        if left[p] > 0:
            picked.append(p)
            left[p] -= 1
    return tuple(picked)


async def old_text(source: Baseline) -> str | None:
    """The baseline's text read back from the archive; None when there is no copy to read."""
    if not source.archive_key:
        return None
    data = await storage.download(storage.SOURCE_ARCHIVE, source.archive_key)
    if data is None:
        return None
    if source.kind != "document":
        return data.decode("utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="source-check-old-") as scratch:
        path = Path(scratch) / storage.filename_from_key(source.archive_key)
        path.write_bytes(data)
        return await asyncio.to_thread(document_text, path)


async def run(checks: list[Check]) -> list[Check]:
    return [await _diff_one(c) if c.status == DIFFERS else c for c in checks]


async def _diff_one(check: Check) -> Check:
    old = await old_text(check.baseline)
    if old is None:
        return replace(check, status=CHANGED, reason="no archived copy to compare with, so assumed changed")
    if not old.strip() and not check.today.text.strip():
        return replace(check, status=CHANGED, old_text=old, reason="a document with no text changed its bytes")
    removed, added = await asyncio.to_thread(diff, old, check.today.text)
    if not removed and not added:
        return replace(check, status=MINOR, old_text=old, reason="only the order or spacing changed")
    return replace(check, old_text=old, removed=removed, added=added,
                   reason=f"{len(removed)} paragraphs removed, {len(added)} added")


def describe(slug: str, checks: list[Check]) -> str:
    lines = [f"{slug}: {counts(checks)}"]
    for c in checks:
        if c.status not in (DIFFERS, MINOR, CHANGED):
            continue
        lines.append(f"  {c.status:10}  {c.baseline.url}  ({c.reason})")
        for sign, side in (("-", c.removed), ("+", c.added)):
            lines += [f"      {sign} {p[:200]}" for p in side[:SHOWN]]
            if len(side) > SHOWN:
                lines.append(f"      {sign} … and {len(side) - SHOWN} more")
    return "\n".join(lines)

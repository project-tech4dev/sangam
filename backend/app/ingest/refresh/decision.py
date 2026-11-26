"""One line per entity: what the check found, and what to do about it. It decides only; it runs nothing."""

from __future__ import annotations

from dataclasses import replace

from app.ingest.refresh.compare import CHANGED, DIFFERS, Check, counts
from app.ingest.refresh.diff import paragraphs
from app.ingest.refresh.discover import NEW, Discovery

NOTHING, REFRESH, FULL_PULL = "nothing to do", "refresh", "full pull"
ACT_ON = ("changed", "dead")  # with any new source, these need the update; unchanged, minor and unverified do not
REDESIGN = 0.5  # more than this share of sources rebuilt at once is a new site, not news on the old one
MIN_REDESIGN_SOURCES = 4  # with fewer, one page edit would already be "most of the site"
REDESIGN_REASON = "most of its sources changed at once, so it was not judged"


def redesigned(checks: list[Check]) -> bool:
    """Read after the diff stage, so a new footer year on every page is not a redesign."""
    if len(checks) < MIN_REDESIGN_SOURCES:
        return False
    return sum(_rebuilt(c) for c in checks) > len(checks) * REDESIGN


def _rebuilt(check: Check) -> bool:
    """Most of the page's old text is gone, not one line of it."""
    return check.status == DIFFERS and len(check.removed) > len(paragraphs(check.old_text or "")) * REDESIGN


def settle(checks: list[Check]) -> list[Check]:
    """A redesign skips the judge, so a page still `differs` is taken as changed: the full pull rereads it anyway."""
    return [replace(c, status=CHANGED, reason=f"{c.reason}; {REDESIGN_REASON}") if c.status == DIFFERS else c
            for c in checks]


def decide(checks: list[Check], found: Discovery, redesign: bool) -> str:
    if redesign:
        return FULL_PULL
    if found.new or any(c.status in ACT_ON for c in checks):
        return REFRESH
    return NOTHING


def describe(slug: str, checks: list[Check], found: Discovery, verdict: str) -> str:
    new = f" · {len(found.new)} {NEW}" if found.new else ""
    return f"{slug}: {counts(checks)}{new} → {verdict}"

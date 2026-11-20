"""Compare today's fingerprint of each source with its baseline: most sources stop here."""

from __future__ import annotations

from dataclasses import dataclass

from app.ingest.refresh.baseline import Baseline
from app.ingest.refresh.fetch_status import OK, Today

UNCHANGED, DIFFERS, MINOR, CHANGED = "unchanged", "differs", "minor", "changed"


@dataclass(frozen=True)
class Check:
    """One source through the check; each stage fills in more of it."""

    baseline: Baseline
    today: Today
    status: str  # unchanged, differs, minor or changed, or the fetch's own unverified or dead
    reason: str = ""
    old_text: str | None = None  # the baseline's text, once the diff stage has read it back
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    verdicts: tuple[tuple[str, str], ...] = ()  # (intact | broken | unanchored, the finding's evidence)


def compare(baselines: list[Baseline], today: list[Today]) -> list[Check]:
    """Pair each baseline with today's fetch of it; a failed fetch keeps its status, so it is never a change."""
    return [Check(b, t, t.status if t.status != OK else UNCHANGED if t.fingerprint == b.text_hash else DIFFERS)
            for b, t in zip(baselines, today, strict=True)]


def counts(checks: list[Check]) -> str:
    tally: dict[str, int] = {}
    for c in checks:
        tally[c.status] = tally.get(c.status, 0) + 1
    return f"{len(checks)} sources · " + " · ".join(f"{n} {s}" for s, n in sorted(tally.items()))


def describe(slug: str, checks: list[Check]) -> str:
    lines = [f"{slug}: {counts(checks)}"]
    for c in checks:
        was = c.baseline.text_hash[:12]
        now = (c.today.fingerprint or "")[:12]
        detail = f"{was} → {now}" if c.status == DIFFERS else was if c.status == UNCHANGED else c.today.reason[:160]
        lines.append(f"  {c.status:10}  {c.baseline.url}  ({detail})")
    return "\n".join(lines)

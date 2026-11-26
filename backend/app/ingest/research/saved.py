"""What saved research holds and leaves open, for research on a later day and the change check."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.ingest.brief import merge_findings
from app.ingest.catalog.writer import slugify
from app.ingest.research.contract import holes, spread, stored

# Newest first, another organisation's (wrong_entity) left out: what research on a later day builds on.
EARLIER_SQL = """
    SELECT slug, entity_kind, status, stopped_reason, findings, gaps, years, supersedes, researched_on
    FROM entity_research
    WHERE slug = %s AND researched_on < current_date AND status <> 'wrong_entity'
    ORDER BY researched_on DESC, researched_at DESC
"""


async def earlier_rows(conn: Any, slug: str) -> list[dict[str, Any]]:
    return [dict(r) for r in await (await conn.execute(EARLIER_SQL, (slug,))).fetchall()]


# By slug, or one name inside the other on word boundaries ("HCL Technologies" for HCL Technologies Limited, never
# "ITC" for Switch Foundation); never trigram similarity, which scores "NRL Foundation" 0.48 against Piramal.
_WORDS = "' ' || trim(regexp_replace(lower({}), '[^a-z0-9]+', ' ', 'g')) || ' '"
# Picks the slug only: names differ between one slug's rows, so its newest row is read by ROW_SQL.
LATEST_SQL = f"""
    SELECT slug, entity_kind FROM entity_research
    WHERE (slug = %(slug)s
           OR {_WORDS.format("entity_name")} LIKE %(within)s OR {_WORDS.format("canonical_name")} LIKE %(within)s
           OR %(words)s LIKE '%%' || {_WORDS.format("COALESCE(canonical_name, entity_name)")} || '%%')
      AND status <> 'wrong_entity' AND entity_kind IN ('funder', 'org')
      AND (%(kind)s::text IS NULL OR entity_kind = %(kind)s)
    ORDER BY slug = %(slug)s DESC, length(COALESCE(canonical_name, entity_name)) DESC,
             researched_on DESC, researched_at DESC
    LIMIT 1
"""
ROW_SQL = """
    SELECT slug, entity_kind, researched_on, gaps, years, COALESCE(canonical_name, entity_name) AS name
    FROM entity_research WHERE slug = %s AND status <> 'wrong_entity' AND (%s::text IS NULL OR entity_kind = %s)
    ORDER BY researched_on DESC, researched_at DESC LIMIT 1
"""
# Oldest first, as merge_findings reads them, so a refresh's removal is applied.
FOUND_SQL = """
    SELECT status, findings, supersedes FROM entity_research
    WHERE slug = %s AND status <> 'wrong_entity' AND entity_kind = %s ORDER BY researched_on, researched_at
"""


# A gap a re-run can fill: the last run stopped before it. One that was read and not stated, or blocked, waits for a
# changed page (the change check) or another source the researcher meets on the way.
RETRY = ("not_reached",)


@dataclass(frozen=True)
class Saved:
    slug: str
    name: str
    entity_kind: str
    researched_on: date
    findings: int
    gaps: list[dict[str, Any]]
    unanswered: list[str]  # fields no saved row answers with a finding or a gap

    @property
    def to_try(self) -> list[str]:
        """What a top-up researcher can answer: fields never answered, a new year among them, and gaps not reached."""
        return [*self.unanswered, *(gap_line(g) for g in self.gaps if g.get("reason") in RETRY)]


async def latest(conn: Any, names: list[str], entity_kind: str | None, wanted: list[str]) -> Saved | None:
    """The newest saved research for any of names, also by a name inside another, and what it leaves open."""
    row = None
    for name in dict.fromkeys(n for n in names if n):
        # Letters and digits only, so nothing in a name is a LIKE wildcard.
        if not (words := " ".join(re.findall(r"[a-z0-9]+", name.lower()))):
            continue
        row = row or await (await conn.execute(LATEST_SQL, {
            "slug": slugify(name), "within": f"% {words} %", "words": f" {words} ", "kind": entity_kind})).fetchone()
    return await by_slug(conn, row["slug"], row["entity_kind"], wanted) if row else None


async def by_slug(conn: Any, slug: str, entity_kind: str | None, wanted: list[str]) -> Saved | None:
    """One slug's newest saved research and what it leaves open; None when there is none."""
    row = await (await conn.execute(ROW_SQL, (slug, entity_kind, entity_kind))).fetchone()
    if not row:
        return None
    rows = [dict(r) for r in await (await conn.execute(FOUND_SQL, (row["slug"], row["entity_kind"]))).fetchall()]
    found = merge_findings(rows)
    gaps = spread(row["gaps"] or [], row["years"] or [])
    return Saved(row["slug"], row["name"], row["entity_kind"], row["researched_on"], len(found), gaps,
                 holes(row["entity_kind"], wanted, stored(found), stored(gaps)))


def gap_line(g: dict[str, Any]) -> str:
    where = " ".join(str(v) for v in (g.get("concept"), g.get("field"), g.get("fiscal_year")) if v)
    return f"{where} ({g.get('reason')})" + (f": {g['detail']}" if g.get("detail") else "")


def goal_lines(saved: Saved | None) -> list[str]:
    """The top-up's goals, for research_goals: the open gaps and unanswered fields, nothing the research holds."""
    if saved is None:
        return []
    out = [(f"\nSaved research for {saved.name} ({saved.slug}), last on {saved.researched_on:%d %b %Y}, holds "
            f"{saved.findings} findings. They are kept: do not look for them again, and a page that research read "
            "answers ALREADY READ. Research ONLY these:")]
    out += [f"    not answered: {m} (record a finding or a gap, or the save is refused)" for m in saved.unanswered]
    out += [f"    not reached: {gap_line(g)}" for g in saved.gaps if g.get("reason") in RETRY]
    if not saved.to_try:
        out.append("    Nothing. Look only for what is newer than that date: a new report, year or call.")
    if settled := [g for g in saved.gaps if g.get("reason") not in RETRY]:
        out.append("Also open, but read before and not stated, or blocked: fill one only from another source you meet "
                   "on the way. A gap you do not fill stays open by itself: do not record it again.")
        out += [f"    {gap_line(g)}" for g in settled]
    return out

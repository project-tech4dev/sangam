"""What saved research holds and leaves open, for research on a later day and the change check."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.ingest.catalog.writer import slugify
from app.ingest.research.contract import holes, stored

# Newest first, another organisation's (wrong_entity) left out: what research on a later day builds on.
EARLIER_SQL = """
    SELECT slug, entity_kind, status, stopped_reason, findings, gaps, researched_on FROM entity_research
    WHERE slug = %s AND researched_on < current_date AND status <> 'wrong_entity'
    ORDER BY researched_on DESC, researched_at DESC
"""


async def earlier_rows(conn: Any, slug: str) -> list[dict[str, Any]]:
    return [dict(r) for r in await (await conn.execute(EARLIER_SQL, (slug,))).fetchall()]


# By slug, or one name inside the other ("HCL Technologies" for HCL Technologies Limited); never trigram similarity,
# which scores "NRL Foundation" 0.48 against "Piramal Foundation".
LATEST_SQL = """
    SELECT slug, entity_kind, researched_on, gaps, COALESCE(canonical_name, entity_name) AS name FROM entity_research
    WHERE (slug = %(slug)s OR entity_name ILIKE %(like)s OR canonical_name ILIKE %(like)s
           OR %(name)s ILIKE '%%' || COALESCE(canonical_name, entity_name) || '%%')
      AND status <> 'wrong_entity' AND entity_kind IN ('funder', 'org')
      AND (%(kind)s::text IS NULL OR entity_kind = %(kind)s)
    ORDER BY slug = %(slug)s DESC, length(COALESCE(canonical_name, entity_name)) DESC,
             researched_on DESC, researched_at DESC
    LIMIT 1
"""
FOUND_SQL = "SELECT findings FROM entity_research WHERE slug = %s AND status <> 'wrong_entity' AND entity_kind = %s"


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
    """The newest saved research for any of names, and what it leaves open; None when there is none."""
    row = None
    for name in dict.fromkeys(n for n in names if n):
        row = row or await (await conn.execute(
            LATEST_SQL, {"slug": slugify(name), "like": f"%{name}%", "name": name, "kind": entity_kind})).fetchone()
    if not row:
        return None
    rows = await (await conn.execute(FOUND_SQL, (row["slug"], row["entity_kind"]))).fetchall()
    found = [f for r in rows for f in (r["findings"] or [])]
    gaps = row["gaps"] or []
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

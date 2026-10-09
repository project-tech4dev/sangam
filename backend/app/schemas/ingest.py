from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import ReadModel


class SourceOut(ReadModel):
    key: str
    name: str
    host: str
    access_rule: str
    basis: str
    categories: list[str]
    yields: list[str]
    dispatchable: bool
    has_adapter: bool
    """Permitted and built are different things: only these are actually fetched."""
    robots_checked_at: str | None = None


class SourceProposalOut(ReadModel):
    id: int
    host: str
    first_seen_url: str | None = None
    robots_result: str | None = None
    times_seen: int
    status: str
    first_seen_at: datetime
    last_seen_at: datetime


class RunOut(ReadModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    added: int = 0
    updated: int = 0
    matched: int = 0
    queued: int = 0
    failed: int = 0
    refused: int = 0


class RunItemOut(ReadModel):
    id: int
    source: str
    record_kind: str
    status: str
    subject: str | None = None
    reason: str | None = None
    target_table: str | None = None
    changes: dict = {}
    match_method: str | None = None
    match_score: float | None = None
    source_url: str | None = None


class QueueItemOut(ReadModel):
    id: int
    raw_name: str
    entity_kind: str
    source: str | None = None
    candidates: list[dict] = []
    source_url: str | None = None
    created_at: datetime


class QueueAnswerIn(BaseModel):
    answer: Literal["same", "different"]
    """same: the name is the candidate's, kept as its alias. different: rejected, nothing joined."""
    candidate_id: int | None = None


class QueueAnswerOut(ReadModel):
    id: int
    status: str


class WorkbookOut(ReadModel):
    """One .xlsx in a bucket, as the spreadsheets card lists it; `path` is what select_source_files takes."""

    path: str
    name: str
    folder: str
    folder_label: str
    size: int | None
    updated_at: str | None


class ResearchOut(ReadModel):
    id: int
    entity_name: str
    canonical_name: str | None = None
    entity_kind: str
    slug: str
    status: str
    stopped_reason: str | None = None
    summary: str
    fact_count: int
    sources_read: list[str] = []
    not_found: list[str] = []
    researched_at: datetime
    saved_at: datetime | None = None
    resolved_org_id: int | None = None
    resolved_funder_id: int | None = None


class CoverageCellOut(ReadModel):
    year: str | None = None
    status: str
    """found, or why not: not_attempted | not_stated | blocked | not_written."""
    detail: str = ""


class CoverageConceptOut(ReadModel):
    concept: str
    title: str
    cells: list[CoverageCellOut]
    fields_filled: int
    fields_total: int
    held: int = 0
    extra_years: list[str] = []
    added: int = 0
    updated: int = 0
    before: int | None = None
    """Catalog rows for this concept before the save; None for an NGO not yet saved."""
    after: int | None = None


class CoverageOut(ReadModel):
    slug: str
    stage: str
    """saved (from what the save recorded) | planned (a funder's dry run) | unsaved (an NGO, no dry run)."""
    saved_at: datetime | None = None
    entity: dict | None = None
    reasons: list[str] = []
    held: list[str] = []
    questions: int = 0
    facts_before: int | None = None
    facts_after: int | None = None
    name: str
    kind: str
    years: list[str]
    write_checked: bool
    cells: int
    found: int
    fields_filled: int
    fields_total: int
    concepts: list[CoverageConceptOut]

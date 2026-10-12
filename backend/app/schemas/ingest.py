from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ReadModel
from app.schemas.me import MeOut


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
    """One .xlsx in a bucket, as the spreadsheets card lists it; `path` is what choose_sources takes as a staff path."""

    path: str
    name: str
    folder: str
    folder_label: str
    size: int | None
    updated_at: str | None


class ReviewFactOut(ReadModel):
    label: str | None
    value: str | float | int
    money: bool


class ReviewAnswerOut(ReadModel):
    concept: str
    topic: str
    year: str | None
    facts: list[ReviewFactOut]
    tag: Literal["confirmed", "self_reported"]
    quote: str
    source_url: str
    source_name: str
    private: bool = False  # from the organisation's own Doc Vault
    held: bool = False  # shown, and not saved to the catalog


class ReviewMissingOut(ReadModel):
    concept: str
    topic: str
    tag: Literal["not_mentioned", "couldnt_read"]
    detail: str


class ReviewFieldOut(ReadModel):
    label: str
    old: Any = None
    new: Any = None
    money: bool


class ReviewChoiceOut(ReadModel):
    value: str
    label: str


class ReviewQuestionOut(ReadModel):
    id: str
    case: int | None
    topic: str
    about: str
    fields: list[ReviewFieldOut]
    stored_as_of: str | None = None
    new_as_of: str | None = None
    stored_name: str | None = None
    new_name: str | None = None
    choices: list[ReviewChoiceOut]


class ReviewSaveOut(ReadModel):
    concept: str
    topic: str
    added: int = 0
    updated: int = 0


class ReviewOut(ReadModel):
    """One researched organisation as the review card shows it: no table or column names."""

    slug: str
    name: str
    kind: str | None
    existing: bool
    answers: list[ReviewAnswerOut]
    missing: list[ReviewMissingOut]
    questions: list[ReviewQuestionOut]
    saves: list[ReviewSaveOut]


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
    # Staff only: the save that still stands, and who made it, for Undo.
    promotion_id: int | None = None
    saved_by: str | None = None


class SaveIn(BaseModel):
    # The person's answer per review question id; a question left out is held, not saved.
    decisions: dict[str, str] = Field(default_factory=dict)


class SavedEntityOut(ReadModel):
    kind: str
    id: int | None = None
    name: str
    status: str | None = None


class SaveOut(ReadModel):
    slug: str
    entity: SavedEntityOut | None = None
    promotion_id: int | None = None
    written: int
    held: int
    reasons: list[str]


class UndoOut(ReadModel):
    promotion_id: int
    slug: str
    removed: int
    restored: int


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


class LiveStepIn(BaseModel):
    """One step from the Working board: which researcher, which tool, still running or not."""

    owner: str | None = Field(default=None, max_length=200)
    tool: str = Field(max_length=80)
    running: bool = False


class AskLiveIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    since: datetime | None = None
    steps: list[LiveStepIn] = Field(default_factory=list, max_length=1000)


class AskLiveOut(ReadModel):
    answer: str
    kind: Literal["status", "instruction"]


class VaultFileOut(ReadModel):
    id: int
    title: str | None = None
    doc_type: str | None = None
    org: str
    org_id: int
    org_name: str


class ImportOverviewOut(ReadModel):
    """Everything the Import page shows on open; the four staff lists are empty for anyone else."""

    me: MeOut
    research: list[ResearchOut]
    vault: list[VaultFileOut]
    sources: list[SourceOut]
    runs: list[RunOut]
    queue: list[QueueItemOut]
    proposals: list[SourceProposalOut]

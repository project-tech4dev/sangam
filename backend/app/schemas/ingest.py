from datetime import datetime

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

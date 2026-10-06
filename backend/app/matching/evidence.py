"""What the engine knows about one org and each funder, loaded once per kind."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.matching.models import Basis, FunderRef, OrgRef


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    basis: Basis
    cite: str
    as_of: str | None = None
    document_id: int | None = None
    valid_until: date | None = None


@dataclass(frozen=True)
class Doc:
    id: int
    doc_type: str
    vault: bool
    """Uploaded through the Vault (uploaded_by set), as opposed to archived by research."""
    title: str | None = None


@dataclass(frozen=True)
class Project:
    source: str
    id: int
    cite: str
    funder: bool = False
    amount: bool = False
    theme: bool = False
    duration: bool = False
    results: bool = False

    def missing(self, fields: tuple[str, ...]) -> list[str]:
        return [f for f in fields if not getattr(self, f)]


@dataclass(frozen=True)
class OrgEvidence:
    org: OrgRef
    districts: dict[int, str] = field(default_factory=dict)
    states: dict[int, str] = field(default_factory=dict)
    """Includes the parent state of every district (R1)."""
    clauses: dict[str, str] = field(default_factory=dict)
    """Schedule VII slug -> label, through tags.meta->>'maps_to'."""
    identifiers: dict[str, Fact] = field(default_factory=dict)
    credential_events: dict[str, Fact] = field(default_factory=dict)
    """The latest event per credential."""
    financials: tuple[Fact, ...] = ()
    board: tuple[Fact, ...] = ()
    documents: dict[str, tuple[Doc, ...]] = field(default_factory=dict)
    projects: tuple[Project, ...] = ()
    not_found: tuple[tuple[str, date], ...] = ()
    """Concepts research looked for and did not find, with the day it looked."""

    @property
    def cite(self) -> str:
        return f"[org:{self.org.id}]"


@dataclass(frozen=True)
class PairFit:
    """Stage 1's row for one funder, relative to one org: what the two share."""

    shared_districts: tuple[str, ...] = ()
    shared_states: tuple[str, ...] = ()
    pan_india: bool = False
    regions: tuple[str, ...] = ()
    stated_places: int = 0
    observed_places: int = 0
    tag_clauses: tuple[str, ...] = ()
    shared_tag_clauses: tuple[str, ...] = ()
    tagged_programmes: int = 0
    shared_programmes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FunderEvidence:
    funder: FunderRef
    fit: PairFit = PairFit()

    @property
    def cite(self) -> str:
        return f"[funder:{self.funder.id}]"

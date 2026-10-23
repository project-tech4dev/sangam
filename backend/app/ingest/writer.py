"""The only code that writes imported data. Fixed SQL, never model-authored."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any, NamedTuple

from psycopg import sql

from app.ingest.expectations import RESERVED_DOC_TYPES
from app.ingest.matcher import TRIGRAM_FLOOR, Match, close_names, name_key
from app.ingest.records import (
    FunderCsrYearRecord,
    FunderRecord,
    OrgFinancialsRecord,
    OrgIdentifierRecord,
    OrgLocationRecord,
    OrgRecord,
)
from app.ingest.taxonomy import TAG_KINDS, TAG_SLUGS


class Owner(NamedTuple):
    """Which side of a shared table a row hangs off.

    programs, metrics, contacts and documents each carry both org_id and
    funder_id under a CHECK that exactly one is set, so the writers that
    target them take the column as well as the id rather than existing twice.
    """

    column: str
    id: int

    @classmethod
    def funder(cls, id: int) -> Owner:
        return cls("funder_id", id)

    @classmethod
    def org(cls, id: int) -> Owner:
        return cls("org_id", id)

# Columns a re-import may overwrite on an existing funder. Everything else on the
# row was either hand-vetted or set by a different source, so an importer leaves it.
FUNDER_UPDATABLE = (
    "funder_type", "website", "section_135_bound", "parent_id", "cin",
    "intake_mode", "funds_external", "typical_duration_months", "grant_size_min", "grant_size_max",
    "legal_form", "founded_year", "registered_address",
    "source_url", "source_name", "fetched_at", "as_of", "content_hash", "extractor_version",
)
# All ten statutory items, not the four this used to carry. The researcher
# collected the other six and promotion dropped them without a word.
CSR_YEAR_UPDATABLE = (
    "prescribed_csr", "total_spent", "average_net_profit", "unspent_transferred",
    "spent_on_projects", "admin_overheads", "impact_assessment_cost", "excess_spent",
    "local_area_spent", "impact_assessment_done", "section_135_applicable", "notes",
    "source_url", "source_name", "fetched_at", "as_of",
)


# Recorded on any tag we attach, because a Schedule VII clause chosen from a
# funder's own wording is an inference and the row should say so.
EXTRACTOR_TAGGER = "sangam-import"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]


def _diff(existing: dict[str, Any], proposed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Columns whose value actually changes; a proposed NULL never erases a value."""
    out: dict[str, dict[str, Any]] = {}
    for col, new in proposed.items():
        if new is None:
            continue
        old = existing.get(col)
        # A jsonb column reads back as a dict or list while the proposed value
        # is the JSON string we are about to send, so a direct comparison is
        # always unequal and every re-run looks like an edit.
        if isinstance(old, dict | list) and isinstance(new, str):
            try:
                same = old == json.loads(new)
            except ValueError:
                same = False
        elif isinstance(old, str) and isinstance(new, str):
            same = old.strip() == new.strip()
        elif old is not None and isinstance(new, int | float) and not isinstance(new, bool):
            # Relative, not absolute: an amount in crore is ~1e8, where a
            # 1e-9 absolute epsilon is far below float precision and every
            # comparison reads as a change.
            old_f, new_f = float(old), float(new)
            same = abs(old_f - new_f) <= 1e-9 * max(1.0, abs(old_f), abs(new_f))
        else:
            same = old == new
        if not same:
            out[col] = {"old": _plain(old), "new": _plain(new)}
    return out


def _plain(v: Any) -> Any:
    return v if v is None or isinstance(v, str | int | float | bool) else str(v)


# --- Update what is clearly the same, ask about the rest ---------------------
#
# docs/features/2026-10-08-import-update-or-ask.md. A Gate, when set, sorts every
# write into five cases; with none set every writer behaves exactly as before.

# A change confined to these is the same fact re-read, never a question.
NOT_FACTS = frozenset({"source_url", "source_name", "fetched_at", "as_of", "content_hash",
                       "extractor_version", "notes", "classification_note"})
# Tables whose rows carry an id, so a question can cite the row and a close match can name it.
HAS_ID = frozenset({"funders", "funder_activity", "programs", "metrics", "contacts", "rfps"})
# Where one real thing can be spelled two ways: table -> (name columns, key columns that must agree).
CLOSE_MATCH = {
    "programs": (("name",), ("funder_id",)),
    "contacts": (("name",), ("funder_id", "role")),
    "funder_activity": (("project_name", "partner_name"), ("funder_id", "kind", "fiscal_year")),
}
CHOICES = {3: ("update", "keep"), 4: ("update", "new", "skip")}
# The funder or programme a plan has not written yet. No row has it, so every lookup under it is new.
UNWRITTEN = -1
_FY = re.compile(r"^FY(\d{4})-\d{2}$")
_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def period_end(value: Any) -> str | None:
    """A comparable ISO date for an as_of: FY2023-24 ends 2024-03-31; 2024-03 and 2024 pad out."""
    if value is None:
        return None
    text = str(value).strip()
    if m := _FY.match(text):
        return f"{int(m[1]) + 1}-03-31"
    if m := _DATE.match(text):
        return f"{m[1]}-{m[2] or '12'}-{m[3] or '31'}"
    return None


# The citation marker each table's rows already carry elsewhere; the table name otherwise.
CITE = {"funders": "funder", "funder_activity": "activity"}


def _cite(table: str, row_id: Any) -> str | None:
    return f"[{CITE.get(table, table)}:{row_id}]" if row_id is not None else None


def _label(key: dict[str, Any]) -> str:
    return " · ".join(str(v) for c, v in key.items() if v is not None and not c.endswith("_id")) or "row"


class Gate:
    """One promotion's decisions. plan=True writes nothing and only records what would happen."""

    def __init__(self, decisions: dict[str, str] | None = None, *, plan: bool = False) -> None:
        self.decisions = dict(decisions or {})
        self.plan = plan
        self.items: list[dict[str, Any]] = []
        self.same = 0

    def _item(self, case: int, table: str, key: dict[str, Any], **extra: Any) -> dict[str, Any]:
        # Not the ids: a programme the plan has not written is UNWRITTEN there and real at apply,
        # and an answer keyed on it would be lost between the two.
        named = {c: v for c, v in key.items() if c not in ("funder_id", "program_id")}
        ident = json.dumps([case, table, named], sort_keys=True, default=str)
        item = {"id": hashlib.sha1(ident.encode()).hexdigest()[:12], "case": case, "table": table,
                "label": _label(key), "row_kind": key.get("kind") or key.get("doc_type"), **extra}
        if case in CHOICES:
            item["choices"] = list(CHOICES[case])
            item["choice"] = self.decisions.get(item["id"])
        self.items.append(item)
        return item

    def on_change(
        self, table: str, key: dict[str, Any], existing: dict[str, Any], changes: dict[str, Any],
        proposed: dict[str, Any],
    ) -> str:
        """update | keep | ask, for a stored row whose values differ from the research."""
        facts = {c: v for c, v in changes.items() if c not in NOT_FACTS}
        if not facts:
            self.same += 1
            return "update"
        old, new = period_end(existing.get("as_of")), period_end(proposed.get("as_of"))
        row = _cite(table, existing.get("id"))
        common = {"row": row, "changes": facts, "stored_as_of": existing.get("as_of"),
                  "new_as_of": proposed.get("as_of")}
        if old and new and new >= old:
            self._item(2, table, key, **common, outcome="planned" if self.plan else "written")
            return "update"
        item = self._item(3, table, key, **common)
        choice = item["choice"] if item["choice"] in CHOICES[3] else None
        item["outcome"] = "asked" if choice is None else ("written" if choice == "update" else "kept")
        if self.plan and choice == "update":
            item["outcome"] = "planned"
        return choice or "ask"

    async def on_new(
        self, conn: Any, table: str, key: dict[str, Any], proposed: dict[str, Any]
    ) -> tuple[str, int | None]:
        """(insert | update | skip | ask, candidate_id) for a row no stored row has the key of."""
        names, agree = CLOSE_MATCH.get(table, ((), ()))
        column = next((c for c in names if key.get(c)), None)
        candidate = None
        if column and key.get("funder_id") not in (None, UNWRITTEN):
            # Column names come from CLOSE_MATCH, never a caller; only values are parameterised.
            where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in agree)
            rows = await (
                await conn.execute(
                    f"SELECT id, {column} AS name, similarity({column}, %s) AS score FROM {table} "
                    f"WHERE {where} AND {column} IS DISTINCT FROM %s AND similarity({column}, %s) >= %s "
                    "ORDER BY score DESC LIMIT 5",
                    (key[column], *(key[c] for c in agree), key[column], key[column], TRIGRAM_FLOOR),
                )
            ).fetchall()
            candidate = next((r for r in rows if close_names(key[column], r["name"])), None)
        if candidate is None:
            self._item(5, table, key, outcome="planned" if self.plan else "written",
                       new={c: _plain(v) for c, v in proposed.items() if v is not None and c not in NOT_FACTS})
            return "insert", None
        item = self._item(
            4, table, key, row=_cite(table, candidate["id"]), column=column,
            stored_name=candidate["name"], new_name=key[column], score=round(float(candidate["score"]), 2),
        )
        choice = self._same_or_not(item)
        return {"update": "update", "new": "insert", "skip": "skip"}.get(choice or "", "ask"), candidate["id"]

    def on_entity(self, table: str, name: str, candidate: dict[str, Any]) -> str:
        """update | new | skip | ask, for research whose name only resembles a stored funder or NGO."""
        item = self._item(4, table, {"name": name}, row=_cite(table, candidate["id"]), column="name",
                          stored_name=candidate["name"], new_name=name, score=candidate.get("score"))
        return self._same_or_not(item) or "ask"

    def _same_or_not(self, item: dict[str, Any]) -> str | None:
        choice = item["choice"] if item["choice"] in CHOICES[4] else None
        item["outcome"] = {"update": "written", "new": "written", "skip": "skipped"}.get(choice or "", "asked")
        if self.plan and choice in ("update", "new"):
            item["outcome"] = "planned"
        return choice

    def asked(self) -> list[dict[str, Any]]:
        return [i for i in self.items if i.get("outcome") == "asked"]


GATE: ContextVar[Gate | None] = ContextVar("import_gate", default=None)


UNTYPED = frozenset({"web_page", "other", None})


async def ensure_document(
    conn: Any, rec: Any, *, owner: Owner | None, doc_type: str,
    storage_path: str | None = None, content_hash: str | None = None,
) -> tuple[int, str]:
    """One documents row per source URL and kind of document (and owner, for a reserved kind).

    The kind is the doc_type itself for the three reserved types and one shared class for every
    other type: a policy page can be both the archived source and the funder's eligibility document
    (two rows), while one PDF that two research runs called 'annual_report' and 'csr_annexure' is
    still one row. Returns (id, added | updated | matched). The archive columns backfill onto a row
    that predates archiving, and only where the row is empty.
    """
    kind = doc_type if doc_type in RESERVED_DOC_TYPES else ""
    # A reserved kind is also per owner: two funders citing one policy page each get their own
    # eligibility text. The column is one of two literals from Owner, never a caller's string.
    mine = f" AND {owner.column} = %s" if kind and owner else ""
    row = await (
        await conn.execute(
            "SELECT id, storage_path, content_hash, doc_type, title FROM documents WHERE source_url = %s "
            "AND (CASE WHEN doc_type = ANY(%s) THEN doc_type ELSE '' END) = %s" + mine
            + " ORDER BY id LIMIT 1",
            (rec.source_url, sorted(RESERVED_DOC_TYPES), kind, *([owner.id] if mine else [])),
        )
    ).fetchone()
    if row:
        # Column names come from this dict, never from a caller; only values
        # are parameterised. Same rule as _upsert.
        fill = {c: v for c, v in
                (("storage_path", storage_path), ("content_hash", content_hash))
                if v and not row[c]}
        # A source first seen only as a cited URL takes the type and title a document finding states.
        if row["doc_type"] in UNTYPED and doc_type not in UNTYPED:
            fill |= {"doc_type": doc_type, "title": getattr(rec, "title", None) or row["title"]}
        if not fill:
            return row["id"], "matched"
        sets = ", ".join(f"{c} = %s" for c in fill)
        await conn.execute(
            f"UPDATE documents SET {sets} WHERE id = %s", (*fill.values(), row["id"])
        )
        return row["id"], "updated"
    # The owner column is one of two literals from Owner, never a caller's
    # string; only values are parameterised. Same rule as _upsert.
    column = owner.column if owner else "funder_id"
    row = await (
        await conn.execute(
            f"INSERT INTO documents ({column}, title, doc_type, source_url, source_name, "
            "fetched_at, as_of, storage_path, content_hash, is_public, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, 'read') RETURNING id",
            (owner.id if owner else None, getattr(rec, "title", None), doc_type, rec.source_url,
             rec.source_name, rec.fetched_at, rec.as_of, storage_path, content_hash),
        )
    ).fetchone()
    return row["id"], "added"


def new_aliases(held: list[str], found: list[str], name: str) -> list[str]:
    """Spellings not already held and not the funder's own name, case-insensitively, in found order."""
    seen = {a.lower() for a in held} | {name.lower()}
    out: list[str] = []
    for alias in found:
        if alias.lower() not in seen:
            seen.add(alias.lower())
            out.append(alias)
    return out


async def write_funder(
    conn: Any, rec: FunderRecord, match: Match, *, parent_id: int | None = None
) -> tuple[str, int, dict]:
    """Returns (status, funder_id, changes). Status is added | updated | matched.

    parent_id is resolved by the caller, which can report a parent it could not find; this writer
    only stores what it is given. Aliases are appended, never replaced: a spelling one source used
    is still a way to find this funder.
    """
    proposed = {
        "funder_type": rec.funder_type, "website": rec.website,
        "section_135_bound": rec.section_135_bound, "parent_id": parent_id, "cin": rec.cin,
        "intake_mode": rec.intake_mode, "funds_external": rec.funds_external,
        "typical_duration_months": rec.typical_duration_months,
        "grant_size_min": rec.grant_size_min, "grant_size_max": rec.grant_size_max,
        "legal_form": rec.legal_form, "founded_year": rec.founded_year,
        "registered_address": rec.registered_address,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    gate = GATE.get()
    if match.resolved:
        existing = await (
            await conn.execute(
                f"SELECT id, name, aliases, {', '.join(FUNDER_UPDATABLE)} FROM funders WHERE id = %s",
                (match.entity_id,),
            )
        ).fetchone()
        changes = _diff({c: existing[c] for c in FUNDER_UPDATABLE}, proposed)
        if changes and gate and gate.on_change(
            "funders", {"name": existing["name"]}, dict(existing), changes, proposed
        ) != "update":
            changes = {}
        held = list(existing["aliases"] or [])
        added = new_aliases(held, rec.aliases, existing["name"])
        if not changes and not added:
            return "matched", match.entity_id, {}
        if gate and gate.plan:
            return "updated", match.entity_id, changes
        sets = [f"{c} = %s" for c in changes]
        values = [proposed[c] for c in changes]
        if added:
            sets.append("aliases = aliases || %s::text[]")
            values.append(added)
            changes["aliases"] = {"old": held, "new": [*held, *added]}
        await conn.execute(
            f"UPDATE funders SET {', '.join(sets)} WHERE id = %s", (*values, match.entity_id)
        )
        return "updated", match.entity_id, changes

    if gate:
        gate._item(5, "funders", {"name": rec.name}, outcome="planned" if gate.plan else "written",
                   new={c: _plain(v) for c, v in proposed.items() if v is not None and c not in NOT_FACTS})
        if gate.plan:
            return "added", UNWRITTEN, {"name": {"old": None, "new": rec.name}}
    slug = await _free_slug(conn, slugify(rec.name))
    row = await (
        await conn.execute(
            "INSERT INTO funders (slug, name, funder_type, website, section_135_bound, parent_id, cin, "
            "aliases, intake_mode, funds_external, typical_duration_months, grant_size_min, "
            "grant_size_max, legal_form, founded_year, registered_address, registry_status, source_url, "
            "source_name, fetched_at, as_of, content_hash, extractor_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'placeholder', "
            "%s, %s, %s, %s, %s, %s) RETURNING id",
            (slug, rec.name, rec.funder_type, rec.website, rec.section_135_bound, parent_id, rec.cin,
             new_aliases([], rec.aliases, rec.name), rec.intake_mode, rec.funds_external,
             rec.typical_duration_months, rec.grant_size_min, rec.grant_size_max,
             rec.legal_form, rec.founded_year, rec.registered_address, rec.source_url, rec.source_name, rec.fetched_at, rec.as_of,
             rec.content_hash, rec.extractor_version),
        )
    ).fetchone()
    return "added", row["id"], {"name": {"old": None, "new": rec.name}}


async def _free_slug(conn: Any, base: str, table: str = "funders") -> str:
    """Table comes from this module, never from a caller."""
    slug, n = base, 2
    while await (
        await conn.execute(f"SELECT 1 FROM {table} WHERE slug = %s", (slug,))
    ).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


async def cin_holder(conn: Any, cin: str) -> dict | None:
    """The funder already holding this CIN, if any. funders.cin is UNIQUE."""
    return await (
        await conn.execute("SELECT id, name FROM funders WHERE cin = %s", (cin,))
    ).fetchone()


async def write_csr_year(
    conn: Any, rec: FunderCsrYearRecord, funder_id: int, document_id: int | None
) -> tuple[str, dict]:
    proposed = {
        "prescribed_csr": rec.prescribed_csr, "total_spent": rec.total_spent,
        "average_net_profit": rec.average_net_profit, "unspent_transferred": rec.unspent_transferred,
        "spent_on_projects": rec.spent_on_projects, "admin_overheads": rec.admin_overheads,
        "impact_assessment_cost": rec.impact_assessment_cost, "excess_spent": rec.excess_spent,
        "local_area_spent": rec.local_area_spent,
        "impact_assessment_done": rec.impact_assessment_done,
        "section_135_applicable": rec.section_135_applicable, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    existing = await (
        await conn.execute(
            f"SELECT {', '.join(CSR_YEAR_UPDATABLE)} FROM funder_csr_years "
            "WHERE funder_id = %s AND fiscal_year = %s",
            (funder_id, rec.fiscal_year),
        )
    ).fetchone()
    gate = GATE.get()
    key = {"funder_id": funder_id, "fiscal_year": rec.fiscal_year}
    if existing is None:
        cols = [c for c in CSR_YEAR_UPDATABLE if proposed[c] is not None]
        if gate:
            gate._item(5, "funder_csr_years", key, outcome="planned" if gate.plan else "written",
                       new={c: _plain(proposed[c]) for c in cols if c not in NOT_FACTS})
            if gate.plan:
                return "added", {}
        await conn.execute(
            f"INSERT INTO funder_csr_years (funder_id, fiscal_year, document_id, {', '.join(cols)}) "
            f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(cols))})",
            (funder_id, rec.fiscal_year, document_id, *[proposed[c] for c in cols]),
        )
        return "added", {c: {"old": None, "new": _plain(proposed[c])} for c in cols}
    changes = _diff(dict(existing), proposed)
    if not changes:
        if gate:
            gate.same += 1
        return "matched", {}
    if gate:
        verdict = gate.on_change("funder_csr_years", key, dict(existing), changes, proposed)
        if verdict != "update":
            return ("kept" if verdict == "keep" else "asked"), {}
        if gate.plan:
            return "updated", changes
    sets = ", ".join(f"{c} = %s" for c in changes)
    await conn.execute(
        f"UPDATE funder_csr_years SET {sets}, document_id = coalesce(document_id, %s) "
        "WHERE funder_id = %s AND fiscal_year = %s",
        (*[proposed[c] for c in changes], document_id, funder_id, rec.fiscal_year),
    )
    return "updated", changes


def _json(v: Any) -> str:
    return json.dumps(v, default=str)


# --- The funder-side fact tables -------------------------------------------
#
# Each follows write_csr_year: an <X>_UPDATABLE allowlist, a SELECT on the
# table's own natural key, _diff, then insert or update. The keys are the
# UNIQUE NULLS NOT DISTINCT constraints the schema already declares, so a
# re-import updates a row rather than growing a second one.

# funder_activity's UNIQUE NULLS NOT DISTINCT key, in its order. `kind` is part of it, so a spend
# line and a partner line that agree on everything else are two lines (0031).
FUNDER_ACTIVITY_KEY = ("funder_id", "kind", "fiscal_year", "program_id", "csr_sector_id",
                       "state_location_id", "location_id", "designation", "project_name", "partner_name")
# is_public is deliberately absent: a new line takes the column's DEFAULT true and no writer updates
# it, so a line a person marked internal (D14) stays internal through every re-promote.
FUNDER_ACTIVITY_UPDATABLE = ("domain_tag_id", "theme_tag_id", "classified_by", "classification_note",
                             "name_as_printed", "implementation_mode", "partner_canonical",
                             "partner_csr1", "partner_kind", "outlay", "amount", "project_count",
                             "is_ongoing", "notes", "source_url", "source_name", "fetched_at", "as_of",
                             "start_date", "end_date", "relationship_status", "partner_org_id",
                             "source_type", "evidence")
_CLASSIFICATION = ("domain_tag_id", "theme_tag_id", "classified_by", "classification_note")
FUNDER_LOCATION_KEY = ("funder_id", "location_id")
FUNDER_LOCATION_UPDATABLE = ("role", "note", "source_url", "source_name", "fetched_at", "as_of")
PROGRAM_KEY = ("funder_id", "name")
PROGRAM_UPDATABLE = ("description", "status", "start_date", "end_date", "parent_id", "kind",
                     "is_enabler", "source_url", "source_name", "fetched_at", "as_of",
                     "content_hash", "extractor_version")
METRIC_KEY = ("funder_id", "name", "period", "program_id")
METRIC_UPDATABLE = ("value", "target", "unit", "stage", "method", "is_self_reported",
                    "baseline", "comparison_value", "chain_key", "sequence", "location_id",
                    "notes", "source_url", "source_name", "fetched_at", "as_of")
CONTACT_KEY = ("funder_id", "name", "role")
CONTACT_UPDATABLE = ("kind", "email", "is_public", "notes",
                     "source_url", "source_name", "fetched_at", "as_of",
                     "content_hash", "extractor_version")


async def _upsert(
    conn: Any, table: str, key: dict[str, Any], updatable: tuple[str, ...],
    proposed: dict[str, Any], document_id: int | None,
) -> tuple[str, dict]:
    """Find the row by its natural key, then insert or diff-update it.

    Table and column names come from the module constants above, never from a
    caller; only values are parameterised.
    """
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
    gate = GATE.get()
    head = "id, " if gate and table in HAS_ID else ""
    existing = await (
        await conn.execute(
            f"SELECT {head}{', '.join(updatable)} FROM {table} WHERE {where}", tuple(key.values())
        )
    ).fetchone()

    if existing is None and gate:
        verdict, candidate = await gate.on_new(conn, table, key, proposed)
        if verdict in ("ask", "skip"):
            return ("asked" if verdict == "ask" else "skipped"), {}
        if verdict == "update":
            return await _rename_into(conn, table, candidate, key, updatable, proposed, document_id, gate)
        if gate.plan:
            return "added", {}

    if existing is None:
        cols = list(key) + [c for c in updatable if proposed.get(c) is not None]
        values = list(key.values()) + [proposed[c] for c in cols[len(key):]]
        if document_id is not None:
            cols.append("document_id")
            values.append(document_id)
        await conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
            tuple(values),
        )
        return "added", {c: {"old": None, "new": _plain(v)} for c, v in zip(cols, values, strict=True)}

    changes = _diff(dict(existing), proposed)
    if not changes:
        if gate:
            gate.same += 1
        return "matched", {}
    if gate:
        verdict = gate.on_change(table, key, dict(existing), changes, proposed)
        if verdict != "update":
            return ("kept" if verdict == "keep" else "asked"), {}
        if gate.plan:
            return "updated", changes
    sets = ", ".join(f"{c} = %s" for c in changes)
    await conn.execute(
        f"UPDATE {table} SET {sets}, document_id = coalesce(document_id, %s) WHERE {where}",
        (*[proposed[c] for c in changes], document_id, *key.values()),
    )
    return "updated", changes


async def _rename_into(
    conn: Any, table: str, row_id: int, key: dict[str, Any], updatable: tuple[str, ...],
    proposed: dict[str, Any], document_id: int | None, gate: Gate,
) -> tuple[str, dict]:
    """A person said the close match is this row: give it the researched key, then the values.

    Refused, not raised, when another row already holds that key: the UNIQUE constraint would
    abort the whole funder's promotion.
    """
    if gate.plan:
        return "updated", {}
    confirmed = ", classification_confirmed" if table == "funder_activity" else ""
    existing = dict(await (
        await conn.execute(
            f"SELECT {', '.join([*key, *updatable])}{confirmed} FROM {table} WHERE id = %s", (row_id,)
        )
    ).fetchone())
    if existing.get("classification_confirmed"):
        proposed = {c: v for c, v in proposed.items() if c not in _CLASSIFICATION}
    # A proposed NULL never erases, so the key the row ends up with keeps the row's own values there.
    target = {c: existing[c] if v is None else v for c, v in key.items()}
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in target)
    taken = await (
        await conn.execute(f"SELECT id FROM {table} WHERE {where} AND id <> %s", (*target.values(), row_id))
    ).fetchone()
    if taken:
        gate.items[-1]["outcome"] = "held"
        gate.items[-1]["reason"] = f"{_cite(table, taken['id'])} already holds that name"
        return "held", {"reason": gate.items[-1]["reason"]}
    wanted = {**target, **proposed}
    changes = _diff(existing, wanted)
    if not changes:
        return "matched", {}
    sets = ", ".join(f"{c} = %s" for c in changes)
    await conn.execute(
        f"UPDATE {table} SET {sets}, document_id = coalesce(document_id, %s) WHERE id = %s",
        (*[wanted[c] for c in changes], document_id, row_id),
    )
    return "updated", changes


def _activity_refusal(key: dict[str, Any], row: dict[str, Any]) -> str | None:
    """funder_activity's CHECKs, asked before the write: a CheckViolation would abort the whole promotion."""
    kind = key["kind"]
    if kind == "spend" and row.get("amount") is None:
        return "a spend line needs an amount"
    if kind == "footprint" and key["location_id"] is None and key["state_location_id"] is None:
        return "a footprint line needs a place"
    if kind == "partner" and key["partner_name"] is None:
        return "a partner line needs the partner's name"
    if kind == "programme" and (key["program_id"] is None or row.get("amount") is None):
        return "a programme line needs a resolved programme and an amount"
    if row.get("domain_tag_id") is not None and row.get("classified_by") is None:
        return "a domain needs classified_by, saying what it rests on"
    return None


async def _write_activity(
    conn: Any, key: dict[str, Any], proposed: dict[str, Any], document_id: int | None
) -> tuple[str, dict]:
    """One funder_activity line. A classification a person confirmed is never re-inferred (D11).
    Returns ("held", {"reason": ...}) for a line the table's CHECKs would refuse."""
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
    row = await (
        await conn.execute(
            f"SELECT classification_confirmed, amount, classified_by FROM funder_activity WHERE {where}",
            tuple(key.values()),
        )
    ).fetchone()
    if row and row["classification_confirmed"]:
        proposed = {c: v for c, v in proposed.items() if c not in _CLASSIFICATION}
    # A proposed NULL never erases, so the row as it will stand is the stored one under the proposal.
    standing = {**(dict(row) if row else {}), **{c: v for c, v in proposed.items() if v is not None}}
    if why := _activity_refusal(key, standing):
        return "held", {"reason": why}
    return await _upsert(conn, "funder_activity", key, FUNDER_ACTIVITY_UPDATABLE, proposed, document_id)


def _activity_key(funder_id: int, kind: str, fiscal_year: str, **ids: Any) -> dict[str, Any]:
    key = dict.fromkeys(FUNDER_ACTIVITY_KEY)
    key.update(funder_id=funder_id, kind=kind, fiscal_year=fiscal_year, **ids)
    return key


async def write_csr_spend(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None, state_id: int | None,
    district_id: int | None, csr_sector_id: int | None, domain_id: int | None,
    theme_id: int | None, document_id: int | None,
) -> tuple[str, dict]:
    key = _activity_key(
        funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
        csr_sector_id=csr_sector_id, state_location_id=state_id, location_id=district_id,
        designation=rec.designation, project_name=rec.project_name, partner_name=rec.partner_name,
    )
    proposed = {
        "domain_tag_id": domain_id, "theme_tag_id": theme_id,
        "classified_by": rec.classified_by, "classification_note": rec.classification_note,
        "implementation_mode": rec.implementation_mode, "partner_csr1": rec.partner_csr1,
        "outlay": rec.outlay, "amount": rec.amount, "project_count": rec.project_count,
        "is_ongoing": rec.is_ongoing, "notes": rec.notes, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _write_activity(conn, key, proposed, document_id)


async def write_footprint(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None,
    state_id: int | None, district_id: int | None, document_id: int | None,
) -> tuple[str, dict]:
    key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
                        state_location_id=state_id, location_id=district_id)
    proposed = {
        "name_as_printed": rec.name_as_printed, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _write_activity(conn, key, proposed, document_id)


async def write_funder_location(
    conn: Any, rec: Any, funder_id: int, *, location_id: int, document_id: int | None
) -> tuple[str, dict]:
    key = {"funder_id": funder_id, "location_id": location_id}
    proposed = {
        "role": rec.role, "note": rec.note, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(
        conn, "funder_locations", key, FUNDER_LOCATION_UPDATABLE, proposed, document_id
    )


# What an organisation's research may not change on a funder's line; a difference is a conflict.
PARTNER_GUARDED = ("amount", "start_date", "end_date", "relationship_status", "source_url")


def _appended(stored: str | None, incoming: str | None) -> str | None:
    """Notes only grow: incoming lines not already stored go after the stored ones."""
    have = {ln.strip() for ln in (stored or "").splitlines()}
    fresh = [ln for ln in (incoming or "").splitlines() if ln.strip() and ln.strip() not in have]
    if not fresh:
        return None
    return "\n".join([stored, *fresh]) if stored else "\n".join(fresh)


async def write_partner(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None, document_id: int | None,
    partner_org_id: int | None = None, fill_only: bool = False, conflicts: list[Conflict] | None = None,
) -> tuple[str, dict]:
    """One partner line; a grant is one, so two projects with one partner in a year are two lines.
    fill_only (an organisation's research) fills blanks and reports a differing value as a conflict."""
    key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
                        project_name=rec.project_name, partner_name=rec.partner_name)
    proposed = {
        "partner_canonical": rec.partner_canonical or rec.partner_name,
        "partner_kind": rec.partner_kind, "partner_csr1": rec.partner_csr1, "partner_org_id": partner_org_id,
        "outlay": rec.outlay, "amount": rec.amount, "start_date": rec.start_date, "end_date": rec.end_date,
        "relationship_status": rec.relationship_status, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "source_type": rec.source_type, "evidence": rec.evidence_tier,
    }
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
    stored = await (
        await conn.execute(f"SELECT id, {', '.join(proposed)} FROM funder_activity WHERE {where}",
                           tuple(key.values()))
    ).fetchone()
    if stored:
        proposed["notes"] = _appended(stored["notes"], rec.notes)
        if rec.source_type and _outranks(stored["source_type"], rec.source_type):
            proposed["source_type"] = proposed["evidence"] = None
        for c in (c for c in proposed if fill_only and c != "notes" and stored[c] is not None):
            if c in PARTNER_GUARDED and _diff({c: stored[c]}, {c: proposed[c]}):
                _sink(conflicts, [Conflict(
                    "funder_activity", f"[activity:{stored['id']}] partner {rec.partner_name!r} {rec.fiscal_year}",
                    c, _plain(stored[c]), None, stored["source_url"], _plain(proposed[c]),
                    getattr(rec, "source_type", None) or "unranked", rec.source_url)])
            proposed[c] = None
    return await _write_activity(conn, key, proposed, document_id)


async def write_programme_spend(
    conn: Any, rec: Any, funder_id: int, *, program_id: int, domain_id: int | None,
    theme_id: int | None, document_id: int | None,
) -> tuple[str, dict]:
    key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id)
    proposed = {
        "domain_tag_id": domain_id, "theme_tag_id": theme_id, "classified_by": rec.classified_by,
        "classification_note": rec.classification_note, "amount": rec.amount, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _write_activity(conn, key, proposed, document_id)


async def write_program(
    conn: Any, rec: Any, owner: Owner, *, parent_id: int | None, document_id: int | None,
    conflicts: list[Conflict] | None = None,
) -> tuple[str, int, dict]:
    """Returns (status, program_id, changes) — the id is needed by every fact
    that names a programme."""
    key = {owner.column: owner.id, "name": rec.name}
    proposed = {
        "description": rec.description, "status": rec.status, "start_date": rec.start_date,
        "end_date": rec.end_date, "parent_id": parent_id, "kind": rec.program_kind,
        "is_enabler": rec.is_enabler, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    if owner.column == "org_id" and rec.source_type is not None:
        status, changes, found = await _upsert_ranked(
            conn, "programs", key, _values(PROGRAM_UPDATABLE), proposed, Tier.of(rec), document_id,
            row=f"[org:{owner.id}] programme {rec.name!r}",
        )
        _sink(conflicts, found)
    else:
        status, changes = await _upsert(
            conn, "programs", key, PROGRAM_UPDATABLE, proposed, document_id
        )
    row = await (
        await conn.execute(
            f"SELECT id FROM programs WHERE {owner.column} = %s AND name = %s",
            (owner.id, rec.name),
        )
    ).fetchone()
    if row is None:
        # Unwritten: planned (a placeholder its facts can key on), or waiting on a person (None).
        gate = GATE.get()
        return status, UNWRITTEN if gate and gate.plan and status in ("added", "updated") else None, changes
    return status, row["id"], changes


async def write_metric(
    conn: Any, rec: Any, owner: Owner, *, program_id: int | None,
    location_id: int | None, document_id: int | None, conflicts: list[Conflict] | None = None,
) -> tuple[str, dict]:
    key = {owner.column: owner.id, "name": rec.name, "period": rec.period,
           "program_id": program_id}
    proposed = {
        "value": rec.value, "target": rec.target, "unit": rec.unit, "stage": rec.stage,
        "method": rec.method, "is_self_reported": rec.is_self_reported,
        "baseline": rec.baseline, "comparison_value": rec.comparison_value,
        "chain_key": rec.chain_key, "sequence": rec.sequence, "location_id": location_id,
        "notes": rec.notes, "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    if owner.column == "org_id" and rec.source_type is not None:
        status, changes, found = await _upsert_ranked(
            conn, "metrics", key, _values(METRIC_UPDATABLE), proposed, Tier.of(rec), document_id,
            row=f"[org:{owner.id}] metric {rec.name!r} {rec.period or ''}".strip(),
        )
        _sink(conflicts, found)
        return status, changes
    return await _upsert(conn, "metrics", key, METRIC_UPDATABLE, proposed, document_id)


async def write_contact(
    conn: Any, rec: Any, owner: Owner, *, document_id: int | None,
    conflicts: list[Conflict] | None = None,
) -> tuple[str, dict]:
    key = {owner.column: owner.id, "name": rec.name, "role": rec.role}
    proposed = {
        "kind": rec.contact_kind, "email": rec.email,
        # A shared mailbox the funder published is public by definition; the
        # column defaults to false and nothing else here sets it.
        "is_public": True if rec.email else None,
        "notes": rec.notes, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    if owner.column == "org_id" and rec.source_type is not None:
        status, changes, found = await _upsert_ranked(
            conn, "contacts", key, _values(CONTACT_UPDATABLE), proposed, Tier.of(rec), document_id,
            row=f"[org:{owner.id}] contact {rec.name!r}",
        )
        _sink(conflicts, found)
        return status, changes
    return await _upsert(conn, "contacts", key, CONTACT_UPDATABLE, proposed, document_id)


RFP_KEY = ("funder_id", "title", "deadline")
RFP_UPDATABLE = ("url", "status", "amount_min", "amount_max", "eligibility",
                 "source_url", "source_name", "fetched_at", "as_of",
                 "content_hash", "extractor_version")


async def write_rfp(
    conn: Any, rec: Any, funder_id: int, *, location_id: int | None,
    tag_id: int | None, document_id: int | None,
) -> tuple[str, int, dict]:
    """A call for proposals, plus where it applies and what theme it is for.

    Returns (status, rfp_id, changes). An RFP with no place attached cannot be
    matched to a client, so rfp_locations and rfp_tags are written here rather
    than left for later.
    """
    key = {"funder_id": funder_id, "title": rec.title, "deadline": rec.deadline}
    proposed = {
        "url": rec.url, "status": rec.status,
        "amount_min": rec.amount_min, "amount_max": rec.amount_max,
        "eligibility": _json({"requirements": rec.eligibility}),
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    status, changes = await _upsert(conn, "rfps", key, RFP_UPDATABLE, proposed, document_id)
    gate = GATE.get()
    if gate and (gate.plan or status in ("asked", "skipped", "kept", "held")):
        return status, None, changes
    row = await (
        await conn.execute(
            "SELECT id FROM rfps WHERE funder_id = %s AND title = %s "
            "AND deadline IS NOT DISTINCT FROM %s",
            (funder_id, rec.title, rec.deadline),
        )
    ).fetchone()
    rfp_id = row["id"]

    if location_id is not None:
        await conn.execute(
            "INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, "
            "fetched_at) VALUES (%s, %s, 'funds', %s, %s, %s) "
            "ON CONFLICT (rfp_id, location_id) DO NOTHING",
            (rfp_id, location_id, rec.source_url, rec.source_name, rec.fetched_at),
        )
    if tag_id is not None:
        await conn.execute(
            "INSERT INTO rfp_tags (rfp_id, tag_id, role, is_inferred, tagged_by) "
            "VALUES (%s, %s, 'primary', true, %s) ON CONFLICT (rfp_id, tag_id) DO NOTHING",
            (rfp_id, tag_id, EXTRACTOR_TAGGER),
        )
    return status, rfp_id, changes


async def write_eligibility_document(conn: Any, rec: Any, funder_id: int) -> tuple[int, str]:
    """The funder's standing eligibility as one documents row, text verbatim (D3).

    Keyed by ensure_document on (source_url, 'funder_eligibility', funder). The text follows the newest
    research, and is_public follows the funder (D14): a hidden funder's guideline is staff-only.
    """
    gate = GATE.get()
    if gate and gate.plan:
        return 0, "planned"
    document_id, status = await ensure_document(
        conn, rec, owner=Owner.funder(funder_id), doc_type=rec.doc_type
    )
    content = rec.content_md()
    changed = await (
        await conn.execute(
            "UPDATE documents d SET content_md = %s, title = %s, as_of = coalesce(%s, d.as_of), "
            "fetched_at = %s, is_public = f.registry_status <> 'hidden' "
            "FROM funders f WHERE d.id = %s AND f.id = d.funder_id "
            "AND (d.content_md IS DISTINCT FROM %s OR d.is_public IS DISTINCT FROM "
            "(f.registry_status <> 'hidden')) RETURNING d.id",
            (content, rec.title, rec.as_of, rec.fetched_at, document_id, content),
        )
    ).fetchone()
    if status == "matched" and changed is not None:
        status = "updated"
    return document_id, status


async def write_funder_tag(conn: Any, funder_id: int, tag_id: int, *, note: str | None) -> None:
    """A theme this funder actually spends on, so field-8 questions can be
    answered from one place instead of aggregated over spend rows.

    is_inferred is always true: the clause was chosen from the funder's own
    wording by a keyword table, and the row should say that rather than read
    as the funder's own classification.
    """
    gate = GATE.get()
    if gate and gate.plan:
        return
    await conn.execute(
        "INSERT INTO funder_tags (funder_id, tag_id, role, is_inferred, tagged_by, note) "
        "VALUES (%s, %s, 'primary', true, %s, %s) "
        "ON CONFLICT (funder_id, tag_id) DO NOTHING",
        (funder_id, tag_id, EXTRACTOR_TAGGER, note),
    )


# The tag table and its subject column, per owner of the tags.
TAG_TABLES = {"program_id": "program_tags", "org_id": "org_tags", "funder_id": "funder_tags"}


async def write_tags(conn: Any, column: str, subject_id: int, rec: Any) -> tuple[int, list[str]]:
    """The record's taxonomy codes onto program_tags, org_tags or funder_tags. Insert-only, so a tag a person set
    stays; is_inferred, since research chose them. An invented code is dropped, never the save.
    Returns (rows added, reasons a code was not written)."""
    gate = GATE.get()
    if gate and gate.plan:
        return 0, []
    added, reasons = 0, []
    for field_name, kinds in TAG_KINDS.items():
        for code in getattr(rec, field_name, None) or []:
            slug = TAG_SLUGS[field_name].get(code)
            if slug is None:
                reasons.append(f"{kinds[0]} {code!r} is not a taxonomy code; dropped")
                continue
            row = await (await conn.execute(
                "SELECT id FROM tags WHERE slug = %s AND status <> 'deprecated'", (slug,)
            )).fetchone()
            if row is None:
                reasons.append(f"{kinds[0]} {code!r} is not in tags (run `make taxonomy-seed`); not written")
                continue
            cur = await conn.execute(
                sql.SQL("INSERT INTO {t} ({c}, tag_id, role, is_inferred, tagged_by, note) "
                        "VALUES (%s, %s, 'primary', true, %s, %s) ON CONFLICT DO NOTHING").format(
                    t=sql.Identifier(TAG_TABLES[column]), c=sql.Identifier(column)),
                (subject_id, row["id"], EXTRACTOR_TAGGER, rec.tag_note),
            )
            added += cur.rowcount
    return added, reasons


async def write_funder_tags_from_programs(conn: Any, funder_id: int) -> int:
    """A funder with no tags of its own takes its programmes' tags, so matching and the registry see a focus."""
    gate = GATE.get()
    if gate and gate.plan:
        return 0
    cur = await conn.execute(
        "INSERT INTO funder_tags (funder_id, tag_id, role, is_inferred, tagged_by, note) "
        "SELECT DISTINCT p.funder_id, pt.tag_id, 'primary', true, %s, 'from its programmes' "
        "FROM program_tags pt JOIN programs p ON p.id = pt.program_id "
        "WHERE p.funder_id = %s AND NOT EXISTS (SELECT 1 FROM funder_tags ft WHERE ft.funder_id = %s) "
        "ON CONFLICT DO NOTHING",
        (EXTRACTOR_TAGGER, funder_id, funder_id),
    )
    return cur.rowcount


# --- The org side ------------------------------------------------------------
# Ranked on the evidence tier (C7): blanks fill, a strictly stronger source replaces, the rest is a Conflict.

# Strongest first. The one place the order lives; seed/seed.py's guard is the 'seed' end of it.
SOURCE_PRECEDENCE: Mapping[str, int] = MappingProxyType({
    "registry": 7, "manual_check": 7, "org_document": 6, "funder": 5,
    "staff_dataset": 4, "prior_research": 3, "aggregator": 2, "seed": 1,
})
# Provenance moves with the tier, only when the incoming source takes the row.
RANKED_PROVENANCE = ("source_url", "source_name", "fetched_at", "as_of", "content_hash", "extractor_version")


class Tier(NamedTuple):
    source_type: str
    evidence: str

    @classmethod
    def of(cls, rec: Any) -> Tier:
        return cls(rec.source_type, rec.evidence_tier)


class Conflict(NamedTuple):
    """A disagreement the writer kept rather than resolved: both values, both sources."""

    table: str
    row: str
    column: str
    stored: Any
    stored_source: str | None
    stored_url: str | None
    incoming: Any
    incoming_source: str
    incoming_url: str | None

    def describe(self) -> str:
        return (
            f"{self.table} {self.row}: {self.column} is {self.stored!r} "
            f"({self.stored_source or 'unranked'}, {self.stored_url or 'no source url'}) and this research "
            f"says {self.incoming!r} ({self.incoming_source}, {self.incoming_url or 'no source url'}). "
            f"The stored value was kept — a person decides."
        )


def _may_overwrite(stored_source: str | None, incoming_source: str) -> bool:
    """Whether incoming_source may replace a DIFFERENT stored value: strictly stronger only.
    NULL stored is unranked (a person's row, or one from before tiers): filled, never overwritten."""
    if incoming_source not in SOURCE_PRECEDENCE:
        raise ValueError(f"unknown source_type {incoming_source!r}")
    if stored_source is None:
        return False
    return SOURCE_PRECEDENCE[incoming_source] > SOURCE_PRECEDENCE[stored_source]


def _outranks(stored_source: str | None, incoming_source: str) -> bool:
    """Whether the stored row's source is strictly stronger than the incoming one."""
    return stored_source is not None and SOURCE_PRECEDENCE[stored_source] > SOURCE_PRECEDENCE[incoming_source]


def _ranked(
    existing: dict[str, Any], proposed: dict[str, Any], stored_source: str | None, incoming_source: str
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, Any, Any]]]:
    """(columns to write as {col: {old, new}}, disagreements kept as (col, stored, incoming))."""
    write: dict[str, dict[str, Any]] = {}
    kept: list[tuple[str, Any, Any]] = []
    for col, new in proposed.items():
        if new is None:
            continue
        old = existing.get(col)
        if old is None:
            write[col] = {"old": None, "new": _plain(new)}
        elif _diff({col: old}, {col: new}):
            if _may_overwrite(stored_source, incoming_source):
                write[col] = {"old": _plain(old), "new": _plain(new)}
            else:
                kept.append((col, _plain(old), _plain(new)))
    return write, kept


def _values(updatable: tuple[str, ...]) -> tuple[str, ...]:
    """An allowlist without its provenance columns, which _upsert_ranked moves with the tier."""
    return tuple(c for c in updatable if c not in RANKED_PROVENANCE)


def _takes_row(stored: dict[str, Any], proposed: dict[str, Any], tier: Tier) -> dict[str, dict[str, Any]]:
    """The tier change when a strictly stronger source states anything on the row, agreeing or not."""
    if not _may_overwrite(stored["source_type"], tier.source_type) or all(v is None for v in proposed.values()):
        return {}
    return {"source_type": {"old": stored["source_type"], "new": tier.source_type},
            "evidence": {"old": stored.get("evidence"), "new": tier.evidence}}


def _sink(conflicts: list[Conflict] | None, found: list[Conflict]) -> None:
    if conflicts is not None:
        conflicts.extend(found)


async def _upsert_ranked(
    conn: Any, table: str, key: dict[str, Any], values: tuple[str, ...], proposed: dict[str, Any],
    tier: Tier, document_id: int | None, *, row: str,
) -> tuple[str, dict, list[Conflict]]:
    """_upsert under the precedence rule. Returns (added | updated | matched, changes, conflicts).
    Table and column names come from module constants; only values are parameterised."""
    provenance = {c: proposed[c] for c in RANKED_PROVENANCE if c in proposed}
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
    existing = await (
        await conn.execute(
            f"SELECT {', '.join(values)}, source_type, evidence, source_url FROM {table} WHERE {where} "
            "FOR UPDATE",
            tuple(key.values()),
        )
    ).fetchone()
    if existing is None:
        fresh = {**key, **{c: proposed[c] for c in values if proposed.get(c) is not None},
                 **{c: v for c, v in provenance.items() if v is not None},
                 "source_type": tier.source_type, "evidence": tier.evidence}
        if document_id is not None:
            fresh["document_id"] = document_id
        await conn.execute(
            f"INSERT INTO {table} ({', '.join(fresh)}) VALUES ({', '.join(['%s'] * len(fresh))})",
            tuple(fresh.values()),
        )
        return "added", {c: {"old": None, "new": _plain(v)} for c, v in fresh.items()}, []

    stored_source = existing["source_type"]
    stated = {c: proposed.get(c) for c in values}
    write, kept = _ranked(dict(existing), stated, stored_source, tier.source_type)
    retier = _takes_row(existing, stated, tier)
    conflicts = [
        Conflict(table, row, c, old, stored_source, existing["source_url"], new, tier.source_type,
                 provenance.get("source_url"))
        for c, old, new in kept
    ]
    if not write and not retier:
        return "matched", {}, conflicts
    sets = {c: proposed[c] for c in write}
    # A weaker or equal source's fill leaves the row's tier and provenance where they were.
    if retier:
        sets.update({c: v for c, v in provenance.items() if v is not None})
        sets.update(source_type=tier.source_type, evidence=tier.evidence)
    await conn.execute(
        f"UPDATE {table} SET {', '.join(f'{c} = %s' for c in sets)}, "
        f"document_id = coalesce(document_id, %s) WHERE {where}",
        (*sets.values(), document_id, *key.values()),
    )
    return "updated", {**write, **retier}, conflicts


ORG_UPDATABLE = ("org_kind", "legal_form", "registration_date", "website", "description",
                 "staff_count", "staff_count_note", "registered_address", "parent_id")
ORG_PROVENANCE = ("source_url", "source_name", "fetched_at", "as_of",
                  "content_hash", "extractor_version")
ORG_FINANCIALS_KEY = ("org_id", "fiscal_year")
ORG_FINANCIALS_VALUES = ("total_income", "program_spend", "non_program_spend", "foreign_contribution",
                         "foreign_unspent", "is_audited", "notes")
ORG_LOCATION_KEY = ("org_id", "location_id")
ORG_LOCATION_VALUES = ("role", "note", "program_id")


async def write_org(
    conn: Any, rec: OrgRecord, match: Match, *, parent_id: int | None = None
) -> tuple[str, int, dict, list[Conflict]]:
    """Returns (status, org_id, changes, conflicts). Status is added | updated | matched.
    Aliases are appended, never replaced, whatever the tier: a spelling a source used still finds the org."""
    proposed = {c: getattr(rec, c, None) for c in ORG_UPDATABLE} | {"parent_id": parent_id}
    provenance = {c: getattr(rec, c) for c in ORG_PROVENANCE}
    tier = Tier.of(rec)
    if match.resolved:
        existing = await (
            await conn.execute(
                f"SELECT name, aliases, source_type, evidence, source_url, {', '.join(ORG_UPDATABLE)} "
                "FROM orgs WHERE id = %s FOR UPDATE",
                (match.entity_id,),
            )
        ).fetchone()
        write, kept = _ranked(dict(existing), proposed, existing["source_type"], tier.source_type)
        conflicts = [
            Conflict("orgs", f"[org:{match.entity_id}]", c, old, existing["source_type"],
                     existing["source_url"], new, tier.source_type, rec.source_url)
            for c, old, new in kept
        ]
        retier = _takes_row(existing, proposed, tier)
        held = list(existing["aliases"] or [])
        added = new_aliases(held, rec.aliases, existing["name"])
        if not write and not added and not retier:
            return "matched", match.entity_id, {}, conflicts
        sets = {c: proposed[c] for c in write}
        if retier:
            sets.update({c: v for c, v in provenance.items() if v is not None})
            sets.update(source_type=tier.source_type, evidence=tier.evidence)
        clauses = [f"{c} = %s" for c in sets]
        values = list(sets.values())
        changes = {**write, **retier}
        if added:
            clauses.append("aliases = aliases || %s::text[]")
            values.append(added)
            changes["aliases"] = {"old": held, "new": [*held, *added]}
        await conn.execute(
            f"UPDATE orgs SET {', '.join(clauses)} WHERE id = %s", (*values, match.entity_id)
        )
        return "updated", match.entity_id, changes, conflicts

    slug = await _free_slug(conn, slugify(rec.name), "orgs")
    row = await (
        await conn.execute(
            "INSERT INTO orgs (slug, name, org_kind, legal_form, registration_date, website, description, "
            "aliases, staff_count, staff_count_note, registered_address, parent_id, registry_status, "
            "source_type, evidence, source_url, source_name, fetched_at, as_of, content_hash, extractor_version) "
            "VALUES (%s, %s, COALESCE(%s, 'cso'), %s, %s, %s, %s, %s, %s, %s, %s, %s, 'placeholder', %s, %s, "
            "%s, %s, %s, %s, %s, %s) RETURNING id",
            (slug, rec.name, rec.org_kind, rec.legal_form, rec.registration_date, rec.website,
             rec.description, new_aliases([], rec.aliases, rec.name), rec.staff_count,
             rec.staff_count_note, rec.registered_address, parent_id, tier.source_type, tier.evidence, *provenance.values()),
        )
    ).fetchone()
    return "added", row["id"], {"name": {"old": None, "new": rec.name}}, []


async def org_alias_holders(conn: Any, spellings: list[str], org_id: int | None) -> dict[str, dict]:
    """name_key(spelling) -> {"id", "name"} of ANOTHER organisation that answers to it, by name or alias.
    Keyed as resolve_org compares, so a spelling it would resolve to that org is caught here too."""
    keys = {name_key(s) for s in spellings if s and name_key(s)}
    if not keys:
        return {}
    texts = sorted({s for s in spellings if s})
    rows = await (
        await conn.execute(
            "SELECT id, name, aliases FROM orgs WHERE id IS DISTINCT FROM %s AND EXISTS ("
            "SELECT 1 FROM unnest(%s::text[]) AS s WHERE lower(name) = lower(s) OR similarity(name, s) >= %s "
            "OR EXISTS (SELECT 1 FROM unnest(aliases) AS a WHERE lower(a) = lower(s) "
            "OR similarity(a, s) >= %s)) ORDER BY id",
            (org_id, texts, TRIGRAM_FLOOR, TRIGRAM_FLOOR),
        )
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        for key in sorted({name_key(n) for n in (r["name"], *(r["aliases"] or []))} & keys):
            out.setdefault(key, {"id": r["id"], "name": r["name"]})
    return out


ORG_IDENTIFIER_VALUES = ("id_value", "status", "valid_from", "valid_until", "application_ref",
                         "check_method", "notes")
# org_identifiers has no content_hash or extractor_version.
ORG_IDENTIFIER_PROVENANCE = ("source_url", "source_name", "fetched_at", "as_of")


async def write_org_identifier(
    conn: Any, rec: OrgIdentifierRecord, org_id: int, document_id: int | None
) -> tuple[str, dict, list[Conflict]]:
    """One registration with its status: (added | updated | matched | held, changes, conflicts).
    Two sources' disagreeing facts are two rows; a strictly stronger source superseding a weaker one is one."""
    cols = ", ".join(ORG_IDENTIFIER_VALUES)
    head = f"SELECT id, org_id, {cols}, source_type, evidence, source_url FROM org_identifiers WHERE "
    proposed = {c: getattr(rec, c) for c in ORG_IDENTIFIER_VALUES}
    provenance = {c: getattr(rec, c) for c in ORG_IDENTIFIER_PROVENANCE}
    tier = Tier.of(rec)

    def conflict(stored: dict, col: str, old: Any, new: Any) -> Conflict:
        return Conflict("org_identifiers", f"[org:{org_id}] {rec.id_type}", col, old, stored["source_type"],
                        stored["source_url"], new, tier.source_type, rec.source_url)

    async def insert(conflicts: list[Conflict]) -> tuple[str, dict, list[Conflict]]:
        fresh = {"org_id": org_id, "id_type": rec.id_type,
                 **{c: v for c, v in proposed.items() if v is not None},
                 **{c: v for c, v in provenance.items() if v is not None},
                 "source_type": tier.source_type, "evidence": tier.evidence, "document_id": document_id}
        await conn.execute(
            f"INSERT INTO org_identifiers ({', '.join(fresh)}) VALUES ({', '.join(['%s'] * len(fresh))})",
            tuple(fresh.values()),
        )
        return "added", {c: {"old": None, "new": _plain(v)} for c, v in fresh.items()}, conflicts

    async def open_row() -> dict | None:
        return await (
            await conn.execute(head + "org_id = %s AND id_type = %s AND id_value IS NULL FOR UPDATE",
                               (org_id, rec.id_type))
        ).fetchone()

    pending: list[Conflict] = []
    if rec.id_value:
        target = await (
            await conn.execute(head + "id_type = %s AND lower(id_value) = lower(%s) FOR UPDATE",
                               (rec.id_type, rec.id_value))
        ).fetchone()
        if target is not None and target["org_id"] != org_id:
            return "held", {}, [conflict(target, "org_id", f"[org:{target['org_id']}]", f"[org:{org_id}]")]
        if target is None:
            target = await open_row()
            # A number fills the open row only when its source supersedes the row's; else it is its own fact.
            if target is not None and not (target["status"] == "check_blocked"
                                           or _may_overwrite(target["source_type"], tier.source_type)):
                differs = target["status"] != rec.status
                return await insert([conflict(target, "status", target["status"], rec.status)] if differs else [])
    elif rec.status == "applied":
        # An application never lands on a number; a live registration of the type is a conflict with it.
        numbered = await (
            await conn.execute(head + "org_id = %s AND id_type = %s AND id_value IS NOT NULL AND is_current "
                               "AND status IN ('registered', 'provisional') ORDER BY id FOR UPDATE",
                               (org_id, rec.id_type))
        ).fetchall()
        found = [conflict(r, "status", f"{r['status']} ({r['id_value']})", "applied") for r in numbered]
        stronger = next((r for r in numbered if _outranks(r["source_type"], tier.source_type)), None)
        if stronger is not None:
            # The registration supersedes the application; only its acknowledgement number may fill a blank.
            if stronger["application_ref"] is None and rec.application_ref:
                await conn.execute("UPDATE org_identifiers SET application_ref = %s WHERE id = %s",
                                   (rec.application_ref, stronger["id"]))
                return "updated", {"application_ref": {"old": None, "new": rec.application_ref}}, found
            return "matched", {}, found
        target = await open_row()
        if target is None:
            return await insert(found)
        pending = found
    else:
        target = await open_row()
        if target is None:
            # A status with no number is about the one current registration of that type, if there is one.
            rows = await (
                await conn.execute(head + "org_id = %s AND id_type = %s AND is_current ORDER BY id LIMIT 2 "
                                   "FOR UPDATE", (org_id, rec.id_type))
            ).fetchall()
            target = rows[0] if len(rows) == 1 else None
    if target is None:
        return await insert([])

    if target["id_value"] is not None:
        proposed["id_value"] = None     # found by its number, case-insensitively: the spelling is not news
    if rec.status == "check_blocked":
        # A check nobody could make confirms nothing: no status, tier, method or provenance moves.
        same = target["status"] == "check_blocked"
        return "matched", {}, pending + ([] if same else [conflict(target, "status", target["status"],
                                                                   "check_blocked")])
    if target["status"] == "check_blocked":
        # A stored blocked check knew nothing, so any real finding takes the row whatever its tier.
        write = {c: {"old": _plain(target[c]), "new": _plain(v)} for c, v in proposed.items()
                 if v is not None and (target[c] is None or _diff({c: target[c]}, {c: v}))}
        retier = {"source_type": {"old": target["source_type"], "new": tier.source_type},
                  "evidence": {"old": target["evidence"], "new": tier.evidence}}
        kept: list[tuple[str, Any, Any]] = []
    else:
        write, kept = _ranked(dict(target), proposed, target["source_type"], tier.source_type)
        retier = _takes_row(target, proposed, tier)
    conflicts = pending + [conflict(target, c, old, new) for c, old, new in kept]
    if not write and not retier:
        return "matched", {}, conflicts
    sets = {c: proposed[c] for c in write}
    if retier:
        sets.update({c: v for c, v in provenance.items() if v is not None})
        sets.update(source_type=tier.source_type, evidence=tier.evidence)
    await conn.execute(
        f"UPDATE org_identifiers SET {', '.join(f'{c} = %s' for c in sets)}, "
        "document_id = coalesce(document_id, %s) WHERE id = %s",
        (*sets.values(), document_id, target["id"]),
    )
    return "updated", {**write, **retier}, conflicts


async def write_org_financials(
    conn: Any, rec: OrgFinancialsRecord, org_id: int, document_id: int | None
) -> tuple[str, dict, list[Conflict]]:
    """One fiscal year on UNIQUE (org_id, fiscal_year). A directory's income never replaces the audited one."""
    return await _upsert_ranked(
        conn, "org_financials", {"org_id": org_id, "fiscal_year": rec.fiscal_year}, ORG_FINANCIALS_VALUES,
        {c: getattr(rec, c) for c in (*ORG_FINANCIALS_VALUES, "source_url", "source_name", "fetched_at",
                                      "as_of")},
        Tier.of(rec), document_id, row=f"[org:{org_id}] {rec.fiscal_year}",
    )


async def write_org_location(
    conn: Any, rec: OrgLocationRecord, org_id: int, *, location_id: int, document_id: int | None,
    program_id: int | None = None,
) -> tuple[str, dict, list[Conflict]]:
    return await _upsert_ranked(
        conn, "org_locations", {"org_id": org_id, "location_id": location_id}, ORG_LOCATION_VALUES,
        {"role": rec.role, "note": rec.note, "program_id": program_id, "source_url": rec.source_url,
         "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of},
        Tier.of(rec), document_id, row=f"[org:{org_id}] location {location_id}",
    )


async def set_registered_location(conn: Any, owner: Owner, location_id: int) -> bool:
    """registered_location_id from a 'registered' place finding: fill-only and untiered, unlike the ranked
    columns beside it. A planned save writes nothing."""
    if (gate := GATE.get()) and gate.plan:
        return False
    table = "orgs" if owner.column == "org_id" else "funders"
    row = await (
        await conn.execute(
            f"UPDATE {table} SET registered_location_id = %s "
            "WHERE id = %s AND registered_location_id IS NULL RETURNING id",
            (location_id, owner.id),
        )
    ).fetchone()
    return row is not None

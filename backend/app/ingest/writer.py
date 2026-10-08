"""The only code that writes imported data. Fixed SQL, never model-authored."""

from __future__ import annotations

import hashlib
import json
import re
from contextvars import ContextVar
from typing import Any, NamedTuple

from app.ingest.expectations import RESERVED_DOC_TYPES
from app.ingest.matcher import TRIGRAM_FLOOR, Match
from app.ingest.records import (
    FunderCsrYearRecord,
    FunderRecord,
    NewsMentionRecord,
    OrgFinancialsRecord,
    OrgLocationRecord,
    OrgRecord,
)


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
        ident = json.dumps([case, table, key], sort_keys=True, default=str)
        item = {"id": hashlib.sha1(ident.encode()).hexdigest()[:12], "case": case, "table": table,
                "label": _label(key), **extra}
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
            candidate = await (
                await conn.execute(
                    f"SELECT id, {column} AS name, similarity({column}, %s) AS score FROM {table} "
                    f"WHERE {where} AND {column} IS DISTINCT FROM %s AND similarity({column}, %s) >= %s "
                    "ORDER BY score DESC LIMIT 1",
                    (key[column], *(key[c] for c in agree), key[column], key[column], TRIGRAM_FLOOR),
                )
            ).fetchone()
        if candidate is None:
            self._item(5, table, key, outcome="planned" if self.plan else "written",
                       new={c: _plain(v) for c, v in proposed.items() if v is not None and c not in NOT_FACTS})
            return "insert", None
        item = self._item(
            4, table, key, row=_cite(table, candidate["id"]), column=column,
            stored_name=candidate["name"], new_name=key[column], score=round(float(candidate["score"]), 2),
        )
        choice = item["choice"] if item["choice"] in CHOICES[4] else None
        item["outcome"] = {"update": "written", "new": "written", "skip": "skipped"}.get(choice or "", "asked")
        if self.plan and choice in ("update", "new"):
            item["outcome"] = "planned"
        return {"update": "update", "new": "insert", "skip": "skip"}.get(choice or "", "ask"), candidate["id"]

    def asked(self) -> list[dict[str, Any]]:
        return [i for i in self.items if i.get("outcome") == "asked"]


GATE: ContextVar[Gate | None] = ContextVar("import_gate", default=None)


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
            "SELECT id, storage_path, content_hash FROM documents WHERE source_url = %s "
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
            "grant_size_max, registry_status, source_url, source_name, fetched_at, as_of, "
            "content_hash, extractor_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'placeholder', "
            "%s, %s, %s, %s, %s, %s) RETURNING id",
            (slug, rec.name, rec.funder_type, rec.website, rec.section_135_bound, parent_id, rec.cin,
             new_aliases([], rec.aliases, rec.name), rec.intake_mode, rec.funds_external,
             rec.typical_duration_months, rec.grant_size_min, rec.grant_size_max,
             rec.source_url, rec.source_name, rec.fetched_at, rec.as_of,
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


async def write_news_mention(
    conn: Any, rec: NewsMentionRecord, funder_id: int | None
) -> tuple[str, dict]:
    existing = await (
        await conn.execute("SELECT id, funder_id FROM news_mentions WHERE url = %s", (rec.url,))
    ).fetchone()
    if existing is None:
        await conn.execute(
            "INSERT INTO news_mentions (url, title, seendate, domain, topic, funder_id, summary, "
            "source_name, fetched_at, review_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')",
            (rec.url, rec.title, rec.seendate, rec.domain, rec.topic, funder_id,
             rec.summary, rec.source_name, rec.fetched_at),
        )
        return "added", {"url": {"old": None, "new": rec.url}}
    if funder_id and existing["funder_id"] is None:
        await conn.execute("UPDATE news_mentions SET funder_id = %s WHERE id = %s",
                           (funder_id, existing["id"]))
        return "updated", {"funder_id": {"old": None, "new": funder_id}}
    return "matched", {}


async def queue_resolution(
    conn: Any, *, raw_name: str, kind: str, match: Match, source: str, rec: Any
) -> int:
    """A name we will not merge on our own. The next run resolves it once accepted."""
    row = await (
        await conn.execute(
            "INSERT INTO resolution_queue (raw_name, entity_kind, candidates, source, context, "
            "source_url, source_name, fetched_at, as_of) "
            "VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s) "
            "ON CONFLICT (entity_kind, raw_name, source) DO UPDATE SET candidates = EXCLUDED.candidates "
            "RETURNING id",
            (raw_name, kind, _json(match.candidates), source,
             _json({"method": match.method, "score": match.score}),
             rec.source_url, rec.source_name, rec.fetched_at, rec.as_of),
        )
    ).fetchone()
    return row["id"]


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
                             "is_ongoing", "notes", "source_url", "source_name", "fetched_at", "as_of")
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
    where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
    taken = await (
        await conn.execute(f"SELECT id FROM {table} WHERE {where} AND id <> %s", (*key.values(), row_id))
    ).fetchone()
    if taken:
        gate.items[-1]["outcome"] = "held"
        gate.items[-1]["reason"] = f"{_cite(table, taken['id'])} already holds that name"
        return "held", {"reason": gate.items[-1]["reason"]}
    existing = await (
        await conn.execute(
            f"SELECT {', '.join([*key, *updatable])} FROM {table} WHERE id = %s", (row_id,)
        )
    ).fetchone()
    changes = _diff(dict(existing), {**key, **proposed})
    if not changes:
        return "matched", {}
    sets = ", ".join(f"{c} = %s" for c in changes)
    await conn.execute(
        f"UPDATE {table} SET {sets}, document_id = coalesce(document_id, %s) WHERE id = %s",
        (*[{**key, **proposed}[c] for c in changes], document_id, row_id),
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


async def write_partner(
    conn: Any, rec: Any, funder_id: int, *, program_id: int | None, document_id: int | None
) -> tuple[str, dict]:
    key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
                        partner_name=rec.partner_name)
    proposed = {
        "partner_canonical": rec.partner_canonical or rec.partner_name,
        "partner_kind": rec.partner_kind, "partner_csr1": rec.partner_csr1,
        "outlay": rec.outlay, "amount": rec.amount, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
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
    conn: Any, rec: Any, owner: Owner, *, parent_id: int | None, document_id: int | None
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
    location_id: int | None, document_id: int | None,
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
    return await _upsert(conn, "metrics", key, METRIC_UPDATABLE, proposed, document_id)


async def write_contact(
    conn: Any, rec: Any, owner: Owner, *, document_id: int | None
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


# --- The org side ------------------------------------------------------------
#
# Same shape as the funder writers, with one deliberate difference: an org that
# already exists is FILLED, not overwritten. The ten cohort rows were vetted by
# hand, so a web page may supply a value nobody has yet and may not replace one
# somebody chose. write_funder has the opposite rule because every funder row
# was machine-made in the first place.

ORG_UPDATABLE = ("org_kind", "legal_form", "registration_date")
ORG_PROVENANCE = ("source_url", "source_name", "fetched_at", "as_of",
                  "content_hash", "extractor_version")
ORG_FINANCIALS_KEY = ("org_id", "fiscal_year")
ORG_FINANCIALS_UPDATABLE = ("total_income", "program_spend", "non_program_spend",
                            "foreign_contribution", "is_audited", "notes",
                            "source_url", "source_name", "fetched_at", "as_of")
ORG_LOCATION_KEY = ("org_id", "location_id")
ORG_LOCATION_UPDATABLE = ("role", "note", "source_url", "source_name", "fetched_at", "as_of")


def _blanks(existing: dict[str, Any], proposed: dict[str, Any]) -> tuple[dict, list[str]]:
    """(what to write, what we refused to overwrite).

    A column is written only where the stored value is NULL. Everything else a
    source disagrees with is returned as prose for a person, because silently
    preferring either one would be a guess dressed as a fact.
    """
    fill, conflicts = {}, []
    for col, new in proposed.items():
        if new is None:
            continue
        old = existing.get(col)
        if old is None:
            fill[col] = {"old": None, "new": _plain(new)}
        elif _diff({col: old}, {col: new}):
            conflicts.append(
                f"{col}: the catalog says {_plain(old)!r} and this research says "
                f"{_plain(new)!r}. The catalog value was kept — a person decides."
            )
    return fill, conflicts


async def write_org(
    conn: Any, rec: OrgRecord, match: Match
) -> tuple[str, int, dict, list[str]]:
    """Returns (status, org_id, changes, conflicts). Status is added | updated | matched.

    Unlike write_funder this returns a fourth value: the stated differences it
    declined to apply, which promotion reports rather than discards.
    """
    proposed = {
        "org_kind": rec.org_kind, "legal_form": rec.legal_form,
        "registration_date": rec.registration_date,
    }
    provenance = {
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
        "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
    }
    if match.resolved:
        existing = await (
            await conn.execute(
                f"SELECT {', '.join(ORG_UPDATABLE)} FROM orgs WHERE id = %s", (match.entity_id,)
            )
        ).fetchone()
        changes, conflicts = _blanks(dict(existing), proposed)
        await _write_org_identifiers(conn, match.entity_id, rec)
        if not changes:
            return "matched", match.entity_id, {}, conflicts
        # Provenance describes the write, not the entity, so it moves with an
        # actual change and stays put when nothing was filled.
        write = {**{c: changes[c]["new"] for c in changes}, **provenance}
        sets = ", ".join(f"{c} = %s" for c in write)
        await conn.execute(
            f"UPDATE orgs SET {sets} WHERE id = %s", (*write.values(), match.entity_id)
        )
        return "updated", match.entity_id, changes, conflicts

    slug = await _free_slug(conn, slugify(rec.name), "orgs")
    row = await (
        await conn.execute(
            "INSERT INTO orgs (slug, name, org_kind, legal_form, registration_date, "
            "registry_status, source_url, source_name, fetched_at, as_of, content_hash, "
            "extractor_version) "
            "VALUES (%s, %s, COALESCE(%s, 'cso'), %s, %s, 'placeholder', %s, %s, %s, %s, %s, "
            "%s) RETURNING id",
            (slug, rec.name, rec.org_kind, rec.legal_form, rec.registration_date,
             *provenance.values()),
        )
    ).fetchone()
    await _write_org_identifiers(conn, row["id"], rec)
    return "added", row["id"], {"name": {"old": None, "new": rec.name}}, []


async def _write_org_identifiers(conn: Any, org_id: int, rec: OrgRecord) -> None:
    """12A, 80G and FCRA among them — the registrations only an NGO carries. `verified` is left at
    its default: research is not verification."""
    for id_type, id_value in rec.identifiers.items():
        await conn.execute(
            "INSERT INTO org_identifiers (org_id, id_type, id_value, source_url, source_name, "
            "fetched_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id_type, id_value) DO NOTHING",
            (org_id, id_type, id_value, rec.source_url, rec.source_name, rec.fetched_at),
        )


async def write_org_financials(
    conn: Any, rec: OrgFinancialsRecord, org_id: int, document_id: int | None
) -> tuple[str, dict]:
    """The org analogue of write_csr_year, on UNIQUE (org_id, fiscal_year)."""
    key = {"org_id": org_id, "fiscal_year": rec.fiscal_year}
    proposed = {
        "total_income": rec.total_income, "program_spend": rec.program_spend,
        "non_program_spend": rec.non_program_spend,
        "foreign_contribution": rec.foreign_contribution,
        "is_audited": rec.is_audited, "notes": rec.notes,
        "source_url": rec.source_url, "source_name": rec.source_name,
        "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(
        conn, "org_financials", key, ORG_FINANCIALS_UPDATABLE, proposed, document_id
    )


async def write_org_location(
    conn: Any, rec: OrgLocationRecord, org_id: int, *, location_id: int, document_id: int | None
) -> tuple[str, dict]:
    key = {"org_id": org_id, "location_id": location_id}
    proposed = {
        "role": rec.role, "note": rec.note, "source_url": rec.source_url,
        "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
    }
    return await _upsert(
        conn, "org_locations", key, ORG_LOCATION_UPDATABLE, proposed, document_id
    )


async def set_registered_location(conn: Any, org_id: int, location_id: int) -> bool:
    """orgs.registered_location_id, from the org_location finding whose role is
    'registered'. Fill-only, like every other column on an existing org."""
    row = await (
        await conn.execute(
            "UPDATE orgs SET registered_location_id = %s "
            "WHERE id = %s AND registered_location_id IS NULL RETURNING id",
            (location_id, org_id),
        )
    ).fetchone()
    return row is not None

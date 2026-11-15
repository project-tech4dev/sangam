"""The only code that writes imported data. Fixed SQL, never model-authored."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any, NamedTuple
from urllib.parse import unquote, urlsplit

from psycopg import sql

from app.ingest.catalog.matcher import TRIGRAM_FLOOR, close_names
from app.ingest.research.expectations import RESERVED_DOC_TYPES
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


# Recorded on any tag we attach, because a Schedule VII clause chosen from a
# funder's own wording is an inference and the row should say so.
EXTRACTOR_TAGGER = "sangam-import"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]


def diff_row(existing: dict[str, Any], proposed: dict[str, Any]) -> dict[str, dict[str, Any]]:
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
            out[col] = {"old": plain(old), "new": plain(new)}
    return out


def plain(v: Any) -> Any:
    return v if v is None or isinstance(v, str | int | float | bool) else str(v)


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
                       new={c: plain(v) for c, v in proposed.items() if v is not None and c not in NOT_FACTS})
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


# Labels a researcher gives a source that say nothing about the page itself.
VAGUE_SOURCE_NAMES = frozenset({"", "research", "indiacsr"})


def cited_title(url: str, source_name: str | None) -> str:
    """A name for a URL cited with no document finding: the researcher's label, else `<host> — <last segment>`."""
    label = (source_name or "").strip()
    if label.lower() not in VAGUE_SOURCE_NAMES:
        return label
    parts = urlsplit(url)
    if not parts.hostname:
        return url
    host = parts.hostname.removeprefix("www.")
    # The Hindu's .../article123.ece is an id; the segment before it is the headline.
    segments = [s for s in unquote(parts.path).split("/") if s and not re.fullmatch(r"article\d+\.ece", s)]
    last = re.sub(r"[-_]+", " ", segments[-1].rsplit(".", 1)[0]).strip() if segments else ""
    return f"{host} — {last[:1].upper()}{last[1:]}" if last else host


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
        # are parameterised. Same rule as upsert.
        fill = {c: v for c, v in
                (("storage_path", storage_path), ("content_hash", content_hash))
                if v and not row[c]}
        # A source first seen only as a cited URL takes the type and title a document finding states.
        if not row["title"] and getattr(rec, "title", None):
            fill["title"] = rec.title
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
    # string; only values are parameterised. Same rule as upsert.
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


async def free_slug(conn: Any, base: str, table: str = "funders") -> str:
    """Table comes from this module, never from a caller."""
    slug, n = base, 2
    while await (
        await conn.execute(f"SELECT 1 FROM {table} WHERE slug = %s", (slug,))
    ).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


CLASSIFICATION = ("domain_tag_id", "theme_tag_id", "classified_by", "classification_note")


async def upsert(
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
        return "added", {c: {"old": None, "new": plain(v)} for c, v in zip(cols, values, strict=True)}

    changes = diff_row(dict(existing), proposed)
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
        proposed = {c: v for c, v in proposed.items() if c not in CLASSIFICATION}
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
    changes = diff_row(existing, wanted)
    if not changes:
        return "matched", {}
    sets = ", ".join(f"{c} = %s" for c in changes)
    await conn.execute(
        f"UPDATE {table} SET {sets}, document_id = coalesce(document_id, %s) WHERE id = %s",
        (*[wanted[c] for c in changes], document_id, row_id),
    )
    return "updated", changes


# The tag table and its subject column, per owner of the tags.
TAG_TABLES = {"program_id": "program_tags", "org_id": "org_tags", "funder_id": "funder_tags"}


async def write_tags(conn: Any, column: str, subject_id: int, rec: Any,
                     role: str = "primary") -> tuple[int, list[str]]:
    """The record's taxonomy codes onto program_tags, org_tags or funder_tags. Insert-only, so a tag a person set
    stays; is_inferred, since research chose them. An invented code is dropped, never the save.
    `secondary` is a programme's tag rolled up to its owner. Returns (rows added, reasons a code was not written)."""
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
                        "VALUES (%s, %s, %s, true, %s, %s) ON CONFLICT DO NOTHING").format(
                    t=sql.Identifier(TAG_TABLES[column]), c=sql.Identifier(column)),
                (subject_id, row["id"], role, EXTRACTOR_TAGGER, rec.tag_note),
            )
            added += cur.rowcount
    return added, reasons


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


def may_overwrite(stored_source: str | None, incoming_source: str) -> bool:
    """Whether incoming_source may replace a DIFFERENT stored value: strictly stronger only.
    NULL stored is unranked (a person's row, or one from before tiers): filled, never overwritten."""
    if incoming_source not in SOURCE_PRECEDENCE:
        raise ValueError(f"unknown source_type {incoming_source!r}")
    if stored_source is None:
        return False
    return SOURCE_PRECEDENCE[incoming_source] > SOURCE_PRECEDENCE[stored_source]


def outranks(stored_source: str | None, incoming_source: str) -> bool:
    """Whether the stored row's source is strictly stronger than the incoming one."""
    return stored_source is not None and SOURCE_PRECEDENCE[stored_source] > SOURCE_PRECEDENCE[incoming_source]


def ranked_changes(
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
            write[col] = {"old": None, "new": plain(new)}
        elif diff_row({col: old}, {col: new}):
            if may_overwrite(stored_source, incoming_source):
                write[col] = {"old": plain(old), "new": plain(new)}
            else:
                kept.append((col, plain(old), plain(new)))
    return write, kept


def ranked_values(updatable: tuple[str, ...]) -> tuple[str, ...]:
    """An allowlist without its provenance columns, which upsert_ranked moves with the tier."""
    return tuple(c for c in updatable if c not in RANKED_PROVENANCE)


def takes_row(stored: dict[str, Any], proposed: dict[str, Any], tier: Tier) -> dict[str, dict[str, Any]]:
    """The tier change when a strictly stronger source states anything on the row, agreeing or not."""
    if not may_overwrite(stored["source_type"], tier.source_type) or all(v is None for v in proposed.values()):
        return {}
    return {"source_type": {"old": stored["source_type"], "new": tier.source_type},
            "evidence": {"old": stored.get("evidence"), "new": tier.evidence}}


def sink_conflicts(conflicts: list[Conflict] | None, found: list[Conflict]) -> None:
    if conflicts is not None:
        conflicts.extend(found)


async def upsert_ranked(
    conn: Any, table: str, key: dict[str, Any], values: tuple[str, ...], proposed: dict[str, Any],
    tier: Tier, document_id: int | None, *, row: str,
) -> tuple[str, dict, list[Conflict]]:
    """upsert under the precedence rule. Returns (added | updated | matched, changes, conflicts).
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
        return "added", {c: {"old": None, "new": plain(v)} for c, v in fresh.items()}, []

    stored_source = existing["source_type"]
    stated = {c: proposed.get(c) for c in values}
    write, kept = ranked_changes(dict(existing), stated, stored_source, tier.source_type)
    retier = takes_row(existing, stated, tier)
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

"""The documents and programmes promote writes before the facts that cite them."""

from __future__ import annotations

import collections
import json
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.ingest.brief import fact_key
from app.ingest.catalog.matcher import name_key
from app.ingest.catalog.promote_records import (
    Mark,
    count_write,
    provenance,
    untiered,
    validated,
    write_record_tags,
)
from app.ingest.catalog.rows import (
    ProgramRecord,
)
from app.ingest.catalog.writer import UNWRITTEN, Conflict, Owner, cited_title, ensure_document, write_tags
from app.ingest.catalog.writer_funder import write_program
from app.ingest.reading import staff_sources, vault
from app.integrations import storage


async def write_documents(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner,
    report: dict[str, Any],
) -> dict[str, int]:
    """Returns source_url -> document id: a row for every public source a fact cites, typed by its
    document finding when there is one."""
    # funders and orgs both key their archive folder on the catalog slug,
    # which is assigned at write time and so is not known before now.
    table = "orgs" if owner.column == "org_id" else "funders"
    slug = (await (await conn.execute(
        f"SELECT slug FROM {table} WHERE id = %s", (owner.id,)
    )).fetchone())["slug"]

    async def document(url: str, title: str | None, source_name: str | None, as_of: str | None,
                       doc_type: str | None) -> tuple[int, str]:
        # Whether the research run archived this URL; Storage being unreachable returns None, never raises.
        key = await storage.archived_key(storage.SOURCE_ARCHIVE, url)
        digest = storage.hash_from_key(key) if key else None
        doc_type = doc_type or ("web_page" if (key or "").endswith(".md") or not _is_file(url) else "other")
        if key:
            key = await _shelve(key, slug, as_of, digest, prefix=table)
        shim = type("Doc", (), {"source_url": url, "title": title, "source_name": source_name or "research",
                                "fetched_at": row["researched_at"], "as_of": as_of})()
        document_id, status = await ensure_document(
            conn, shim, owner=owner, doc_type=doc_type,
            storage_path=storage.qualify(storage.SOURCE_ARCHIVE, key) if key else None, content_hash=digest,
        )
        report.setdefault("documents", {})[url] = {"id": document_id, "doc_type": doc_type, "title": title}
        count_write(report, "documents", status)
        return document_id, status

    by_url: dict[str, int] = {}
    for f in validated(findings, "document", report):
        mark = Mark(report)
        if _private(f.source_url):
            # the private row exists; ensure_document would add a public one
            report["held"].append("document: skipped: private document already on file")
            mark.settle(f, "skipped")
            continue
        document_id, status = await document(f.source_url, f.title, f.source_name, f.as_of, f.doc_type)
        by_url[f.source_url] = document_id
        mark.settle(f, status, f"[documents:{document_id}]")
    for f in findings:
        url = f.get("source_url")
        if f.get("concept") and url and url not in by_url and not _private(url):
            by_url[url], _ = await document(url, cited_title(url, f.get("source_name")), f.get("source_name"),
                                            None, None)
    by_url.update(await _staff_datasets(conn, findings))
    by_url.update(await vault.document_rows(conn, findings))
    return by_url


_FILES = frozenset({"pdf", "xls", "xlsx", "csv", "doc", "docx", "ppt", "pptx", "zip"})


def _is_file(url: str) -> bool:
    """A URL naming a downloadable file rather than a page: an annual report's .pdf, a .xlsx."""
    last = urlsplit(url).path.rsplit("/", 1)[-1]
    return "." in last and last.rsplit(".", 1)[-1].lower() in _FILES


def _private(url: str | None) -> bool:
    return staff_sources.is_staff_source_url(url) or vault.is_vault_url(url)


async def write_document_links(
    conn: Any, findings: list[dict[str, Any]], owner: Owner, programs: Programmes, docs: dict[str, int],
    report: dict[str, Any],
) -> None:
    """One link per document, owner, programme and year, from every fact written or confirmed."""
    links: dict[tuple, list[str]] = {}
    described = report.get("documents", {})
    for f in findings:
        key = json.dumps(list(fact_key(f)))
        settled = report.get("facts", {}).get(key)
        document_id = docs.get(f.get("source_url"))
        if settled is None or document_id is None:
            continue
        # The brief lists each source from its facts' states; one key can hold the fact from several sources,
        # so the state maps each source to its document. A new dict: one state can be shared by several facts.
        url = f["source_url"]
        settled = report["facts"][key] = {**settled, "documents": {
            **settled.get("documents", {}), url: [document_id, described.get(url, {}).get("doc_type")]}}
        if settled.get("state") not in ("written", "confirms"):
            continue
        named = f.get("name") if f.get("concept") == "program" else f.get("program_name")
        pages = links.setdefault((document_id, programs.get(named), f.get("fiscal_year")), [])
        if f.get("page") and f["page"] not in pages:
            pages.append(f["page"])
    for (document_id, program_id, year), pages in links.items():
        await conn.execute(
            f"INSERT INTO document_links (document_id, {owner.column}, program_id, fiscal_year, pages) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (document_id, org_id, funder_id, program_id, fiscal_year) "
            "DO UPDATE SET pages = ARRAY(SELECT DISTINCT unnest(document_links.pages || excluded.pages))",
            (document_id, owner.id, program_id, year, pages),
        )
    if links:
        report["written"].setdefault("document_links", collections.Counter())["written"] += len(links)


async def _staff_datasets(conn: Any, findings: list[dict[str, Any]]) -> dict[str, int]:
    """source_url -> the private row of each staff dataset cited, so its lines carry document_id."""
    return {url: row["id"] for url, row in (await staff_dataset_rows(conn, findings)).items()}


async def staff_dataset_rows(conn: Any, findings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """source_url -> the staff dataset row it names, with what is needed to re-open the workbook."""
    urls = sorted({
        f["source_url"] for f in findings if staff_sources.is_staff_source_url(f.get("source_url"))
    })
    if not urls:
        return {}
    rows = await (await conn.execute(
        "SELECT id, source_url, source_name, storage_path, content_hash FROM documents "
        "WHERE doc_type = 'source_dataset' AND source_url = ANY(%s) ORDER BY id",
        (urls,),
    )).fetchall()
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        found.setdefault(row["source_url"], dict(row))
    return found


async def _shelve(
    key: str, slug: str, as_of: str | None, digest: str | None, *, prefix: str = "funders"
) -> str:
    """Move a just-archived object to a name a person can read, now that the
    funder is known. Returns wherever the object actually ended up.

    Fetching cannot name the file: `fetch_document` runs during research, so it
    has only the URL and the bytes to key on. Promotion has the funder and the
    period, which is what makes `funders/<slug>/2023-annual-report.pdf`
    possible. The leftovers are informative — an object still under a hash
    folder is one we downloaded and no finding ever cited.
    """
    destination = storage.catalog_key(slug, as_of, storage.filename_from_key(key), prefix=prefix)
    if destination == key:
        return key
    # Same funder, same year, same published filename, different bytes. Rare,
    # and silently overwriting one with the other would lose a source.
    if await storage.stat(storage.SOURCE_ARCHIVE, destination) is not None:
        destination = storage.catalog_key(
            slug, as_of, storage.filename_from_key(key), suffix=(digest or "")[:8],
            prefix=prefix,
        )
    return destination if await storage.move(
        storage.SOURCE_ARCHIVE, key, destination
    ) else key


# "Mission 2 Million (2019-2025)"; "SLP - Rural Livelihoods"; "Rural Livelihoods (SLP component)".
_PAREN = re.compile(r"\s*\(([^)]*)\)\s*$")


_PREFIX = re.compile(r"^([A-Z][A-Z0-9&]{1,9})\s*[-–:]\s+(.+)$")


_SMALL = frozenset({"of", "the", "and", "for", "in", "a"})


def programme_key(name: str) -> str:
    """A programme's name as it is matched: no trailing parenthetical, no `ABBR - ` prefix."""
    bare = _PAREN.sub("", name).strip() or name
    m = _PREFIX.match(bare)
    return name_key(m[2] if m else bare)


def _abbreviation(name: str) -> str | None:
    """The parent a spend line names by its initials: SLP in "SLP - Rural Livelihoods" or "(SLP component)"."""
    bare = _PAREN.sub("", name).strip()
    if m := _PREFIX.match(bare):
        return m[1]
    paren = _PAREN.search(name)
    word = paren and re.match(r"([A-Z][A-Z0-9&]{1,9})\b", paren[1])
    return word[1] if word else None


def _initials(name: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in _SMALL).upper()


class Programmes:
    """One owner's programmes by programme_key: those written this run, then those already stored."""

    def __init__(self, stored: dict[str, tuple[int, str]]) -> None:
        self.stored = stored
        self.ids: dict[str, int] = {}
        self.names: dict[str, str] = {}
        self.held: dict[str, str] = {}

    @classmethod
    async def load(cls, conn: Any, owner: Owner) -> Programmes:
        rows = await (await conn.execute(
            f"SELECT id, name FROM programs WHERE {owner.column} = %s ORDER BY id", (owner.id,)
        )).fetchall()
        stored: dict[str, tuple[int, str]] = {}
        for r in rows:
            stored.setdefault(programme_key(r["name"]), (r["id"], r["name"]))
        return cls(stored)

    def get(self, name: str | None, default: int | None = None) -> int | None:
        if not name:
            return default
        key = programme_key(name)
        if key in self.ids:
            return self.ids[key]
        return self.stored[key][0] if key in self.stored else default

    def name(self, name: str) -> str:
        """The spelling the row has, or will have: a stored or just-written one wins over this one."""
        key = programme_key(name)
        return self.names.get(key) or (self.stored[key][1] if key in self.stored else name)

    def why_not(self, name: str) -> str:
        return self.held.get(programme_key(name)) or "no programme of that name was researched or is held"

    def by_initials(self, abbreviation: str) -> tuple[int, str] | None:
        found = {(i, n) for k, i in self.ids.items() if _initials(n := self.names[k]) == abbreviation}
        found |= {v for v in self.stored.values() if _initials(v[1]) == abbreviation}
        return found.pop() if len(found) == 1 else None


def _parents_first(found: list[Any]) -> list[Any]:
    """Shallowest kind first, and a programme after the programme it names as parent, whatever their kinds."""
    depth = {"theme": 0, "programme": 1, "component": 2, "phase": 2, "project": 3}
    pending = sorted(found, key=lambda f: depth.get(f.kind, 9))
    out: list[Any] = []
    while pending:
        waiting = {programme_key(f.name) for f in pending}
        ready = [f for f in pending if not f.parent_name or programme_key(f.parent_name) not in waiting
                 or programme_key(f.parent_name) == programme_key(f.name)]
        ready = ready or pending[:1]  # a cycle: write one, and its parent lookup decides
        out += ready
        pending = [f for f in pending if f not in ready]
    return out


async def write_programs(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner,
    docs: dict[str, int], report: dict[str, Any],
) -> Programmes:
    """Every programme, parents first, so later concepts can resolve program_name; a held parent holds its children."""
    programs = await Programmes.load(conn, owner)
    conflicts: list[Conflict] = []
    for f in _parents_first(validated(findings, "program", report)):
        mark = Mark(report, conflicts)
        key = programme_key(f.name)
        if key in programs.names:
            # "Mission 2 Million (2019-2025)" after "Mission 2 Million": one programme, written once.
            mark.settle(f, "matched", f"[programs:{programs.ids[key]}]" if programs.ids[key] != UNWRITTEN else None)
            continue
        if untiered(owner, f, f"programme {f.name!r}", report):
            programs.held[key] = "its own finding has no evidence tier"
            mark.settle(f, None)
            continue
        parent_id = programs.get(f.parent_name)
        if f.parent_name and parent_id is None:
            why = f"its parent {f.parent_name!r} is not in Sangam ({programs.why_not(f.parent_name)})"
            report["held"].append(f"programme {f.name!r}: {why}; held with it rather than written with no parent.")
            programs.held[key] = why
            mark.settle(f, None)
            continue
        status, program_id = await _write_program(
            conn, row, f, programs.name(f.name), f.kind, parent_id, owner, docs, report, conflicts)
        if program_id is None:
            programs.held[key] = "it is waiting for a person" if status == "asked" else "it was not written"
        else:
            programs.ids[key], programs.names[key] = program_id, programs.name(f.name)
        mark.settle(f, status, f"[programs:{program_id}]" if program_id not in (None, UNWRITTEN) else None)
    await _write_components(conn, row, findings, owner, programs, docs, report, conflicts)
    report["conflicts"].extend(c.describe() for c in conflicts)
    return programs


async def _write_program(
    conn: Any, row: dict[str, Any], f: Any, name: str, kind: str, parent_id: int | None, owner: Owner,
    docs: dict[str, int], report: dict[str, Any], conflicts: list[Conflict],
) -> tuple[str | None, int | None]:
    try:
        rec = ProgramRecord(
            entity_name=row["canonical_name"] or row["entity_name"], name=name,
            program_kind=kind, description=getattr(f, "description", None), status=getattr(f, "status", None),
            start_date=getattr(f, "start_date", None), end_date=getattr(f, "end_date", None),
            is_enabler=getattr(f, "is_enabler", None),
            themes=getattr(f, "themes", None) or [], populations=getattr(f, "populations", None) or [],
            lenses=getattr(f, "lenses", None) or [], tag_note=getattr(f, "tag_note", None),
            source_type=getattr(f, "source_type", None), evidence_tier=getattr(f, "evidence_tier", None),
            as_of=None, **provenance(f, row["researched_at"]),
        )
    except ValidationError as exc:
        report["held"].append(f"programme {name!r}: {exc.errors()[0]['msg']}")
        return None, None
    status, program_id, _ = await write_program(
        conn, rec, owner, parent_id=parent_id, document_id=docs.get(f.source_url), conflicts=conflicts,
    )
    count_write(report, "programs", status)
    await write_record_tags(conn, "program_id", program_id, rec, f"programme {name!r}", report)
    if program_id not in (None, UNWRITTEN):
        # The Registry reads only the owner's tags; a code the programme refused is already reported.
        added, _ = await write_tags(conn, owner.column, owner.id, rec, role="secondary")
        if added:
            report["written"].setdefault("tags", collections.Counter())["added"] += added
    return status, program_id


async def _write_components(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], owner: Owner, programs: Programmes,
    docs: dict[str, int], report: dict[str, Any], conflicts: list[Conflict],
) -> None:
    """A spend line naming no programme, but its parent by initials, is a component of that parent.
    "SLP - Ecosystem Action" with no such programme becomes "Ecosystem Action" under Sustainable Livelihood Programme."""
    for f in validated([f for f in findings if f.get("concept") == "programme_spend"], "programme_spend"):
        if programs.get(f.program_name) is not None or not (abbreviation := _abbreviation(f.program_name)):
            continue
        parent = programs.by_initials(abbreviation)
        if parent is None:
            continue
        key = programme_key(f.program_name)
        name = _PREFIX.sub(r"\2", _PAREN.sub("", f.program_name).strip())
        _, program_id = await _write_program(
            conn, row, f, name, "component", parent[0], owner, docs, report, conflicts)
        if program_id is not None:
            programs.ids[key], programs.names[key] = program_id, name

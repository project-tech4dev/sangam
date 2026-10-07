"""Staff-only source workbooks: where they live, how they are read, how a fact from one is cited.

Confidential: nothing here logs or returns an error carrying a cell value."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
from collections import OrderedDict
from collections.abc import Iterable
from pathlib import PurePath
from typing import Any

from app.integrations import storage
from app.repositories import documents as documents_repo
from app.repositories import funders as funders_repo

logger = logging.getLogger(__name__)

DOC_TYPE = "source_dataset"
SOURCE_URL_PREFIX = "https://staff-sources.sangam.invalid/"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def dataset_id(filename: str) -> str:
    """A file's identity is its base name, so a corrected re-upload replaces it."""
    return hashlib.sha256(PurePath(filename).name.encode()).hexdigest()[:12]


def object_key(source_key: str, filename: str) -> str:
    return f"{source_key}/{dataset_id(filename)}.xlsx"


def source_url(filename: str) -> str:
    """http(s) as findings require; resolves nowhere (RFC 2606) and names no file."""
    return SOURCE_URL_PREFIX + dataset_id(filename)


def is_staff_source_url(url: str | None) -> bool:
    return bool(url) and str(url).startswith(SOURCE_URL_PREFIX)


def title(source_key: str, filename: str) -> str:
    return f"Staff dataset · {source_key} · {dataset_id(filename)}"


HEADER_ROWS = 3            # top rows of a sheet shown with any match
SECTION_ROWS = 40          # rows a matching numbered heading brings with it
MAX_CHARS = 60_000         # ~15k tokens of tool output
CONTACT_HEADERS = ("phone", "mobile", "email", "e mail", "contact person", "address")
_SUFFIXES = {"ltd", "limited", "pvt", "private"}
_NON_WORD = re.compile(r"[^\w]+")
_NUMBERED = re.compile(r"^\s*\d+\s*[.)]\s*\S")
_EMAIL = re.compile(r"\S+@\S+\.\w+")
_CACHE_MAX_BYTES = 200 * 1024 * 1024
_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}


def _words(value: Any) -> str:
    return " ".join(_NON_WORD.sub(" ", str(value).casefold()).split())


def search_terms(names: Iterable[str | None]) -> list[str]:
    terms: list[str] = []
    for name in names:
        words = _words(name or "").split()
        while words and words[-1] in _SUFFIXES:
            words.pop()
        if words and words[0] == "the":
            words.pop(0)
        term = " ".join(words)
        if len(term) >= 3 and term not in terms:
            terms.append(term)
    return terms


def _hit(value: Any, terms: list[str]) -> bool:
    if not isinstance(value, str):
        return False
    padded = f" {_words(value)} "
    return any(f" {t} " in padded for t in terms)


def _contact_columns(values: tuple) -> set[int]:
    return {c for c, v in enumerate(values, start=1)
            if isinstance(v, str) and any(f" {h} " in f" {_words(v)} " for h in CONTACT_HEADERS)}


def scan(data: bytes, terms: list[str], only_sheet: str = "") -> list[tuple[str, list[tuple[int, tuple]], set[int]]]:
    """Per sheet with a match: its title, the rows to show (header, context, matches), and contact columns."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    try:
        for ws in wb.worksheets:
            if only_sheet and only_sheet.casefold() not in ws.title.casefold():
                continue
            ws.reset_dimensions()  # some exports carry a wrong <dimension>; read_only trusts it otherwise
            rows: dict[int, tuple] = {}
            drop: set[int] = set()
            numbered = heading = under = None
            section_left, matched, seen = 0, False, 0
            for r, values in enumerate(ws.iter_rows(values_only=True), start=1):
                filled = [v for v in values if v not in (None, "")]
                if not filled:
                    continue
                seen += 1
                hit = any(_hit(v, terms) for v in filled)
                if seen <= HEADER_ROWS:  # shown always; a match here still counts (data can start on row 2)
                    rows[r] = values
                    drop |= _contact_columns(values)
                    matched = matched or hit
                    continue
                if heading and under is None and r == heading[0] + 1:
                    under = (r, values)
                    drop |= _contact_columns(values)
                if len(filled) == 1:
                    heading, under = (r, values), None
                    if _NUMBERED.match(str(filled[0])):
                        numbered, section_left = (r, values), (SECTION_ROWS if hit else 0)
                if hit or section_left:
                    for ctx in (numbered, heading, under):
                        if ctx:
                            rows.setdefault(*ctx)
                    rows[r] = values
                    matched = matched or hit
                    section_left = max(section_left - 1, 0)
            if matched:
                out.append((ws.title, sorted(rows.items()), drop))
    finally:
        wb.close()
    return out


def _cell(value: Any) -> str:
    text = " ".join(str(value).split())
    return "[email removed]" if _EMAIL.search(text) else text[:300]


def render(doc: dict[str, Any], sheets: list[tuple[str, list[tuple[int, tuple]], set[int]]]) -> str:
    from openpyxl.utils import get_column_letter

    lines = [f"## document {doc['id']} · {doc['source_name']}",
             f"A finding from it: source_url {doc['source_url']} · source_name {doc['source_name']}"]
    for title, rows, drop in sheets:
        lines.append(f"### sheet {title!r}")
        for r, values in rows:
            cells = [(f"{get_column_letter(c)}{r}", v) for c, v in enumerate(values, start=1)
                     if v not in (None, "") and c not in drop]
            if cells:
                body = " · ".join(f"{ref}={_cell(v)!r}" for ref, v in cells)
                lines.append(f"[source:{doc['id']}#{title}!{cells[0][0]}] {body}")
    return "\n".join(lines)


async def _workbook(doc: dict[str, Any]) -> bytes | None:
    """The workbook's bytes, downloaded once per process and per upload (content_hash)."""
    parts = storage.split(doc["storage_path"] or "")
    if parts is None or parts[0] != storage.STAFF_SOURCES:
        return None
    key = (doc["storage_path"], doc["content_hash"] or "")
    async with _locks.setdefault(doc["storage_path"], asyncio.Lock()):
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        data = await storage.download(*parts, max_bytes=storage.STAFF_SOURCES_MAX_BYTES)
        if data is None:
            return None
        _cache[key] = data
        while len(_cache) > 1 and sum(len(b) for b in _cache.values()) > _CACHE_MAX_BYTES:
            _cache.popitem(last=False)
        return data


async def read_rows(pool: Any, name: str, *, sheet: str = "") -> str:
    name = (name or "").strip()
    funders = await funders_repo.name_variants(pool, match=name) if len(name) >= 3 else []
    terms = search_terms([name, *(n for f in funders for n in (f["name"], *(f["aliases"] or [])))])
    if not terms:
        return "read_source_rows needs a name of at least three letters."
    datasets = await documents_repo.list_source_datasets(pool)
    if not datasets:
        return "No staff dataset is uploaded (make staff-source). Nothing was read."
    parts: list[str] = []
    problems: list[str] = []
    for doc in datasets:
        data = await _workbook(doc)
        if data is None:
            problems.append(f"document {doc['id']} ({doc['source_name']}) could not be downloaded.")
            continue
        try:
            sheets = await asyncio.to_thread(scan, data, terms, sheet)
        except Exception as exc:  # noqa: BLE001 - type only: a message could quote a cell
            problems.append(f"document {doc['id']} ({doc['source_name']}) could not be read ({type(exc).__name__}).")
            continue
        if sheets:
            parts.append(render(doc, sheets))
    logger.info("read_source_rows: %d of %d datasets matched", len(parts), len(datasets))
    head = [f"read_source_rows: {len(parts)} of {len(datasets)} staff datasets name one of: {'; '.join(terms)}."]
    if not parts:
        head.append("No row matched. The filer is often the parent company, not the foundation: try its "
                    "registered name.")
        return "\n".join(head + problems)
    head.append("Cite a fact by the marker of the cell that holds it: [source:<document>#<sheet>!<cell>]. "
                "Amounts are as printed; the sheet's unit is in your skill's sheet notes.")
    text = "\n\n".join(["\n".join(head), *parts, *problems])
    if len(text) > MAX_CHARS:
        cut = text.rfind("\n", 0, MAX_CHARS)
        text = (text[:cut] + f"\n… output cut at {MAX_CHARS} characters. Call again with `sheet` "
                "(e.g. one fiscal year) to read the rest.")
    return text

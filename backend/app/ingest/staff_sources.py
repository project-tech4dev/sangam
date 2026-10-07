"""Staff-only source workbooks: where they live, how they are read, how a fact from one is cited.

Confidential: nothing here logs or returns an error carrying a cell value."""

from __future__ import annotations

import hashlib
from pathlib import PurePath

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

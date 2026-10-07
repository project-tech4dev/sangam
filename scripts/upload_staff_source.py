"""Upload one staff-only workbook to the private staff-sources bucket (spec §4).

    make staff-source ENV=staging FILE="<path>.xlsx" KEY=<registry key>

Service key, staff-run. Re-uploading the same file name replaces the object and updates its row.
Prints counts only, never a cell, a sheet name or the file name.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest import staff_sources
from app.ingest.sources import SOURCES
from app.integrations import storage
from app.repositories import documents as documents_repo


def _sheet_count(data: bytes) -> int:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return len(wb.worksheets)
    finally:
        wb.close()


async def main(path: Path, source_key: str) -> int:
    settings = get_settings()
    if not settings.storage_enabled:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set: staff datasets live only in Storage.")
        return 2
    if source_key not in SOURCES:
        print(f"{source_key!r} is not a registered source key.")
        return 2
    data = path.read_bytes()
    if len(data) > storage.STAFF_SOURCES_MAX_BYTES:
        print(f"{len(data) / 1024 / 1024:.1f} MB is over the 100 MB staff-sources limit.")
        return 2
    try:
        sheets = _sheet_count(data)
    except Exception as exc:  # noqa: BLE001 - any openpyxl failure means "not a workbook we can read"
        print(f"not a readable .xlsx workbook ({type(exc).__name__}); nothing stored.")
        return 2
    key = staff_sources.object_key(source_key, path.name)
    stored = await storage.upload(storage.STAFF_SOURCES, key, data, staff_sources.XLSX, replace=True,
                                  max_bytes=storage.STAFF_SOURCES_MAX_BYTES)
    if stored is None:
        print("storing the workbook failed - does 0032's bucket exist, and is the project's global "
              "upload limit at least 100 MB?")
        return 1
    pool = make_pool(settings.database_url, max_size=2)
    await pool.open()
    try:
        document_id, status = await documents_repo.upsert_source_dataset(
            pool, title=staff_sources.title(source_key, path.name), source_key=source_key,
            storage_path=storage.qualify(storage.STAFF_SOURCES, key),
            source_url=staff_sources.source_url(path.name), content_hash=storage.content_hash(data),
        )
    finally:
        await pool.close()
    print(f"{status}: document {document_id} · {storage.qualify(storage.STAFF_SOURCES, key)} · {sheets} sheets")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--source-key", required=True, help="registry key, e.g. mca_csr")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.file, args.source_key)))

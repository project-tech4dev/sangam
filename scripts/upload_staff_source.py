"""Upload one staff-only workbook to the private staff-sources bucket (spec §4).

    make staff-source ENV=staging FILE="<path>.xlsx" KEY=<registry key>

Service key, staff-run. Re-uploading the same file name replaces the object and updates its row.
Prints counts only, never a cell, a sheet name or the file name.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest import staff_sources
from app.ingest.sources import SOURCES
from app.integrations import storage
from app.repositories import documents as documents_repo
from psycopg.conninfo import conninfo_to_dict


def _sheet_count(data: bytes) -> int:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return len(wb.worksheets)
    finally:
        wb.close()


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}


def _refusal(database_url: str) -> str | None:
    """Storage is global, so only a managed database may pair with it."""
    if os.environ.get("STAFF_SOURCE_ENV") != "staging":
        return "run this through `make staff-source ENV=staging` (STAFF_SOURCE_ENV=staging)."
    try:
        host = (conninfo_to_dict(database_url).get("host") or "").split(",")[0]
    except Exception as exc:  # noqa: BLE001 - the type only; the DSN holds a password
        return f"DATABASE_URL could not be parsed ({type(exc).__name__})."
    if not host or host.startswith("/") or host in _LOCAL_HOSTS:
        return "DATABASE_URL points at a local database; refusing, since Storage is global."
    return None


async def main(path: Path, source_key: str) -> int:
    settings = get_settings()
    if (reason := _refusal(settings.database_url)):
        print(reason)
        return 2
    if not settings.storage_enabled:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set: staff datasets live only in Storage.")
        return 2
    if source_key not in SOURCES:
        print(f"{source_key!r} is not a registered source key.")
        return 2
    try:
        size = path.stat().st_size
    except OSError:
        print("the file could not be found or read.")
        return 2
    if size > storage.STAFF_SOURCES_MAX_BYTES:
        print(f"{size / 1024 / 1024:.1f} MB is over the 100 MB staff-sources limit.")
        return 2
    try:
        data = path.read_bytes()
    except OSError:
        print("the file could not be found or read.")
        return 2
    try:
        sheets = _sheet_count(data)
    except Exception as exc:  # noqa: BLE001 - any openpyxl failure means "not a workbook we can read"
        print(f"not a readable .xlsx workbook ({type(exc).__name__}); nothing stored.")
        return 2
    key = staff_sources.object_key(source_key, path.name)
    pool = make_pool(settings.database_url, max_size=2)
    try:
        await pool.open()
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        print(f"the database is unreachable ({type(exc).__name__}); nothing stored.")
        return 1
    try:
        stored = await storage.upload(storage.STAFF_SOURCES, key, data, staff_sources.XLSX, replace=True,
                                      max_bytes=storage.STAFF_SOURCES_MAX_BYTES)
        if stored is None:
            print("the upload failed - check that the bucket exists, its size limit and the service key.")
            return 1
        try:
            document_id, status = await documents_repo.upsert_source_dataset(
                pool, title=staff_sources.title(source_key, path.name), source_key=source_key,
                storage_path=storage.qualify(storage.STAFF_SOURCES, key),
                source_url=staff_sources.source_url(path.name), content_hash=storage.content_hash(data),
            )
        except Exception:  # noqa: BLE001
            print("object stored, row not written - re-run to retry.")
            return 1
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

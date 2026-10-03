"""Move archived documents from their fetch-time key to their catalog name.

`fetch_document` keys an object on the URL and its bytes, because during
research nobody knows yet which funder it belongs to. Promotion renames it to
`funders/<slug>/<year>-<filename>` once it does. This catches the ones that
were archived before promotion learned to do that, and would catch them again
if the naming ever changes.

Reads `documents`, so it only touches objects the catalog actually cites — an
object still under a hash folder after this ran is one no finding referenced.

    python -m app.ingest.reshelve              # dry run
    python -m app.ingest.reshelve --yes        # move them
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import psycopg
from psycopg.rows import dict_row

from app.ingest.promote import _shelve
from app.integrations import storage

SQL = """
SELECT d.id, d.storage_path, d.as_of, d.content_hash, f.slug
FROM documents d
JOIN funders f ON f.id = d.funder_id
WHERE d.storage_path LIKE %s
ORDER BY f.slug, d.id
"""


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="move; otherwise dry run")
    args = parser.parse_args()

    if not storage.get_settings().storage_enabled:
        print("Supabase Storage is not configured — nothing to do", file=sys.stderr)
        return 1
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    async with await psycopg.AsyncConnection.connect(url, row_factory=dict_row) as conn:
        rows = await (
            await conn.execute(SQL, (f"{storage.SOURCE_ARCHIVE}/%",))
        ).fetchall()

        moved = skipped = failed = 0
        for row in rows:
            parts = storage.split(row["storage_path"])
            if parts is None:
                continue
            _, key = parts
            if key.startswith("funders/"):
                skipped += 1
                continue

            destination = await _shelve(key, row["slug"], row["as_of"], row["content_hash"]) \
                if args.yes else storage.catalog_key(
                    row["slug"], row["as_of"], storage.filename_from_key(key)
                )
            if destination == key:
                print(f"  ! {row['id']:>4}  could not move  {key}")
                failed += 1
                continue
            print(f"  {'→' if args.yes else '·'} {row['id']:>4}  {destination}")
            moved += 1
            if args.yes:
                await conn.execute(
                    "UPDATE documents SET storage_path = %s WHERE id = %s",
                    (storage.qualify(storage.SOURCE_ARCHIVE, destination), row["id"]),
                )
        if args.yes:
            await conn.commit()

    verb = "moved" if args.yes else "would move"
    print(f"\n{verb} {moved}, already shelved {skipped}, failed {failed}")
    if not args.yes and moved:
        print("dry run — nothing moved. Re-run with --yes.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

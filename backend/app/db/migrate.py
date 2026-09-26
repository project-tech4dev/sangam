"""Forward-only SQL migration runner.

Why not Alembic: this codebase deliberately uses raw psycopg with hand-written
SQL and no ORM, so there are no models for Alembic to autogenerate from. What
remains of Alembic in that setup is a version table and an ordered file list,
which is what this module is.

Contract:
  - db/migrations/NNNN_name.sql, applied in filename order, one transaction each.
  - Each applied file is recorded in schema_migrations with a checksum. Editing
    an already-applied file is reported as drift rather than silently ignored.
  - db/init/02_schema.sql remains the baseline for a brand-new database; this
    runner carries every change made after that baseline.

Usage (both work against the bundled *and* an external DATABASE_URL):
    python -m app.db.migrate --status
    python -m app.db.migrate
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(os.environ.get("MIGRATIONS_DIR", "/srv/db/migrations"))

VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def say(msg: str) -> None:
    # flush: stdout is block-buffered when piped, which would otherwise print
    # progress lines after the stderr failure they preceded.
    print(msg, flush=True)


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()[:16]


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    status_only = "--status" in sys.argv

    if not MIGRATIONS_DIR.is_dir():
        print(f"no migrations directory at {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))

    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute(VERSION_TABLE)
        conn.commit()

        applied = {
            row[0]: row[1]
            for row in conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
        }

        pending = []
        for path in files:
            version, sql = path.stem, path.read_text()
            digest = _checksum(sql)
            if version in applied:
                if applied[version] != digest:
                    # Loud, but not fatal: the DB is already in the edited
                    # file's intended end state only if someone applied it by
                    # hand. Surfacing it beats pretending the file is current.
                    say(f"  ! {version} — DRIFT: file changed after it was applied")
                else:
                    say(f"  = {version} (applied {'' if status_only else 'earlier'})")
                continue
            pending.append((version, sql, digest, path))

        if not pending:
            say("nothing pending — database is up to date")
            return 0

        if status_only:
            for version, _, _, _ in pending:
                say(f"  + {version} (pending)")
            say(f"{len(pending)} migration(s) pending")
            return 0

        for version, sql, digest, path in pending:
            try:
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (version, digest),
                    )
            except Exception as exc:  # noqa: BLE001 — report which file, then stop
                print(f"  x {version} FAILED — rolled back: {exc}", file=sys.stderr)
                print("no further migrations were attempted", file=sys.stderr)
                return 1
            say(f"  + {version} applied")

        say(f"{len(pending)} migration(s) applied")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

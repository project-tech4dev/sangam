"""Forward-only SQL migration runner."""

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


def migrate_checkpointer(url: str, *, status_only: bool) -> None:
    """LangGraph's own tables, after ours. Here, not at boot, so a langgraph upgrade migrates once, on purpose."""
    from langgraph.checkpoint.postgres import PostgresSaver

    from app.db.checkpointer import CHECKPOINT_VERSION

    with PostgresSaver.from_conn_string(url) as saver:
        if status_only:
            conn = saver.conn
            exists = conn.execute("SELECT to_regclass('checkpoint_migrations') AS t").fetchone()["t"]
            at = conn.execute("SELECT max(v) AS v FROM checkpoint_migrations").fetchone()["v"] if exists else None
            state = "up to date" if at == CHECKPOINT_VERSION else "pending"
            say(f"  checkpointer v{at if at is not None else '-'} of v{CHECKPOINT_VERSION} ({state})")
            return
        saver.setup()
        say(f"  checkpointer at v{CHECKPOINT_VERSION}")


def main() -> int:
    code = _apply_sql()
    if code == 0:
        migrate_checkpointer(os.environ["DATABASE_URL"], status_only="--status" in sys.argv)
    return code


def _apply_sql() -> int:
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
                    # Loud, but not fatal: the DB is already in the edited file's intended end state only if
                    # someone applied it by hand. Surfacing it beats pretending the file is current.
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

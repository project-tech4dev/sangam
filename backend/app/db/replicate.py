"""Copy one database's data into another that already has the same schema.

Sibling of migrate.py: migrations carry the shape, this carries the contents.
Built for the case that actually comes up — research runs against the local
Postgres and the result has to reach the managed one — so the source is
authoritative and the target's rows for a copied table are replaced.

It is not a merge. A table listed here ends up holding exactly the source's
rows, with the source's ids, which is what keeps every foreign key valid with
no remapping pass. Tables are ordered by their dependencies and the whole run
is one transaction, so a failure anywhere leaves the target as it was.

    python -m app.db.replicate                 # dry run: the plan and the counts
    python -m app.db.replicate --yes           # do it

The target is DATABASE_URL, so the compose overlay picks it the same way it
does for migrate.py; the source is REPLICATE_SOURCE_URL.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from io import BytesIO

import psycopg

# LangGraph's runtime state and the migration ledger. The target keeps its own
# ledger because it applied its own migrations, and chat checkpoints belong to
# the deployment that created them.
EXCLUDED = ("schema_migrations", "checkpoints", "checkpoint_blobs",
            "checkpoint_writes", "checkpoint_migrations")

TABLES_SQL = """
SELECT c.relname AS name
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> ALL(%s)
ORDER BY c.relname
"""

EDGES_SQL = """
SELECT conrelid::regclass::text AS child, confrelid::regclass::text AS parent
FROM pg_constraint
WHERE contype = 'f' AND connamespace = 'public'::regnamespace
"""

COLUMNS_SQL = """
SELECT table_name, column_name FROM information_schema.columns
WHERE table_schema = 'public' ORDER BY table_name, ordinal_position
"""


def ordered(tables: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Parents before children, so a copy never lands on a missing reference.

    A self-reference is skipped rather than treated as a cycle: foreign-key
    triggers fire at the end of a statement, so one COPY carrying a whole tree
    of locations or programmes checks out fine.
    """
    known = set(tables)
    needs: dict[str, set[str]] = defaultdict(set)
    for child, parent in edges:
        if child in known and parent in known and child != parent:
            needs[child].add(parent)

    out: list[str] = []
    remaining = set(tables)
    while remaining:
        ready = sorted(t for t in remaining if not (needs[t] - set(out)))
        if not ready:
            raise SystemExit(f"foreign-key cycle among: {sorted(remaining)}")
        out.extend(ready)
        remaining -= set(ready)
    return out


def schema_of(conn: psycopg.Connection) -> dict[str, list[str]]:
    shape: dict[str, list[str]] = defaultdict(list)
    for table, column in conn.execute(COLUMNS_SQL).fetchall():
        shape[table].append(column)
    return dict(shape)


def counts(conn: psycopg.Connection, tables: list[str]) -> dict[str, int]:
    return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def _plan(source: psycopg.Connection, only: str | None) -> list[str]:
    tables = [r[0] for r in source.execute(TABLES_SQL, (list(EXCLUDED),)).fetchall()]
    if only:
        wanted = {t.strip() for t in only.split(",") if t.strip()}
        unknown = wanted - set(tables)
        if unknown:
            raise SystemExit(f"not copyable: {', '.join(sorted(unknown))}")
        tables = [t for t in tables if t in wanted]
    edges = [tuple(r) for r in source.execute(EDGES_SQL).fetchall()]
    return ordered(tables, edges)


def _copy(source: psycopg.Connection, target: psycopg.Connection, table: str) -> None:
    """Binary COPY, so types cross exactly and nothing needs escaping."""
    buffer = BytesIO()
    with source.cursor().copy(f'COPY "{table}" TO STDOUT (FORMAT BINARY)') as out:
        for chunk in out:
            buffer.write(chunk)
    buffer.seek(0)
    with target.cursor().copy(f'COPY "{table}" FROM STDIN (FORMAT BINARY)') as into:
        into.write(buffer.read())


def _resync_sequence(target: psycopg.Connection, table: str) -> None:
    """An identity column keeps its own counter, and copied ids do not move it.
    Without this the next insert on the target collides with a copied row.
    """
    rows = target.execute(
        "SELECT a.attname, pg_get_serial_sequence(%s, a.attname) "
        "FROM pg_attribute a "
        "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped "
        "  AND pg_get_serial_sequence(%s, a.attname) IS NOT NULL",
        (table, table, table),
    ).fetchall()
    for column, sequence in rows:
        target.execute(
            f'SELECT setval(%s, coalesce((SELECT max("{column}") FROM "{table}"), 1))',
            (sequence,),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="write; otherwise dry run")
    parser.add_argument("--only", help="comma-separated subset of tables")
    args = parser.parse_args()

    target_url = os.environ.get("DATABASE_URL", "")
    source_url = os.environ.get("REPLICATE_SOURCE_URL", "")
    if not target_url or not source_url:
        print("set DATABASE_URL (target) and REPLICATE_SOURCE_URL (source)", file=sys.stderr)
        return 2
    if target_url == source_url:
        print("source and target are the same database", file=sys.stderr)
        return 2

    with psycopg.connect(source_url) as source, psycopg.connect(target_url) as target:
        # Identical shape is the precondition the whole approach rests on: ids
        # cross verbatim, so a column the target lacks is a silent loss.
        src_shape, tgt_shape = schema_of(source), schema_of(target)
        if src_shape != tgt_shape:
            print("schemas differ — run the migrations first", file=sys.stderr)
            for label, names in (
                ("source only", sorted(set(src_shape) - set(tgt_shape))),
                ("target only", sorted(set(tgt_shape) - set(src_shape))),
                ("different columns", sorted(t for t in set(src_shape) & set(tgt_shape)
                                             if src_shape[t] != tgt_shape[t])),
            ):
                if names:
                    print(f"  {label}: {', '.join(names)}", file=sys.stderr)
            return 1

        plan = _plan(source, args.only)
        before_src, before_tgt = counts(source, plan), counts(target, plan)
        print(f"{len(plan)} table(s), {sum(before_src.values()):,} row(s) to copy\n")
        print(f"  {'table':32} {'source':>9} {'target now':>11}")
        for table in plan:
            if before_src[table] or before_tgt[table]:
                print(f"  {table:32} {before_src[table]:>9,} {before_tgt[table]:>11,}")
        print(f"\n  untouched: {', '.join(EXCLUDED)}")

        if not args.yes:
            print("\ndry run — nothing written. Re-run with --yes.")
            return 0

        # One transaction: a failure at table 20 of 28 must not leave the
        # target half replaced.
        with target.transaction():
            for table in reversed(plan):
                target.execute(f'DELETE FROM "{table}"')
            for table in plan:
                _copy(source, target, table)
            for table in plan:
                _resync_sequence(target, table)

        after = counts(target, plan)
        wrong = {t: (before_src[t], after[t]) for t in plan if before_src[t] != after[t]}
        print(f"\ncopied {sum(after.values()):,} row(s)")
        if wrong:
            print(f"MISMATCH after copy: {wrong}", file=sys.stderr)
            return 1
        print("every table matches the source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

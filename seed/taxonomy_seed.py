"""Seed the Schedule VII CSR vocabulary.

`db/migrations/0002_taxonomy.sql` widened `tags.kind` to allow `'csr_sector'`
and its header promised `python -m seed.taxonomy_seed`. The module never
existed, so nothing ever pointed `funder_csr_spend.csr_sector_id` at anything
and every promoted spend row left it NULL.

Schedule VII is a closed statutory list, which is exactly what makes it safe to
normalise against. A funder's own words for a theme stay on the row; this is
only the shelf they are filed under.

Idempotent: run it as often as you like.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import psycopg

DATA = pathlib.Path(__file__).parent / "data" / "taxonomy" / "schedule_vii.json"


def seed_schedule_vii(cur) -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    rows = payload["categories"]
    for order, category in enumerate(rows):
        cur.execute(
            """
            INSERT INTO tags (slug, label, kind, code, description, sort_order, status)
            VALUES (%s, %s, 'csr_sector', %s, %s, %s, 'active')
            ON CONFLICT (slug) DO UPDATE SET
                label = EXCLUDED.label,
                kind = EXCLUDED.kind,
                code = EXCLUDED.code,
                description = EXCLUDED.description,
                sort_order = EXCLUDED.sort_order
            """,
            (
                f"csr-{category['slug']}",
                category["label"],
                category["code"],
                f"Schedule VII clause ({category['code']}). {payload['source_url']}",
                order,
            ),
        )
    return len(rows)


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        count = seed_schedule_vii(cur)
        conn.commit()
    print(f"seeded: {count} Schedule VII categories as tags(kind='csr_sector')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

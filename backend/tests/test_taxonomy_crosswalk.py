"""0022: every sector tag says which Schedule VII clause it maps to, or that it maps to none."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.ingest.taxonomy import CLAUSES

MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "0022_taxonomy_crosswalk.sql"

# One VALUES row per line: ('slug', 'label', 'sector', '{"maps_to": ...}')
ROW = re.compile(r"\('([^']+)',\s*'((?:[^']|'')+)',\s*'sector',\s*'(\{[^']*\})'\)")


def _sql() -> str:
    if not MIGRATION.exists():
        pytest.skip("migration not reachable from here")
    return MIGRATION.read_text(encoding="utf-8")


def _rows() -> list[tuple[str, str, dict]]:
    return [(s, label.replace("''", "'"), json.loads(meta)) for s, label, meta in ROW.findall(_sql())]


def _slugify(label: str) -> str:
    # seed/seed.py:38 — the seed derives the slug from the label, so the two must agree here.
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


class TestCrosswalkMigrationShape:
    def test_inserts_rather_than_updates(self):
        # migrate runs before seed inserts the sector tags, so an UPDATE matches nothing on a fresh database.
        sql = _sql()
        assert "ON CONFLICT (slug)" in sql
        assert not re.search(r"\bUPDATE\s+tags\b", sql, re.IGNORECASE)

    def test_every_row_decides_a_clause(self):
        rows = _rows()
        assert len(rows) == 40
        assert all("maps_to" in meta for _, _, meta in rows)

    def test_every_clause_is_a_schedule_vii_slug(self):
        known = {slug for slug, _ in CLAUSES}
        mapped = {meta["maps_to"] for _, _, meta in _rows() if meta["maps_to"] is not None}
        assert mapped <= known, f"not a csr_sector slug: {sorted(mapped - known)}"

    def test_slugs_are_the_seeds_own(self):
        # A slug one character off never conflicts, and a fresh database gets a second, bare tag.
        wrong = [(slug, label) for slug, label, _ in _rows() if slug != _slugify(label)]
        assert not wrong

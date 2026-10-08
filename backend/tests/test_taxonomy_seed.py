"""The theme taxonomy seed: what the files turn into, and that it lands in tags and tag_links."""

import json
import os
import pathlib
import sys
from collections import Counter

import psycopg
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # repo root, for `seed`

from seed.taxonomy_seed import DATA, TAXONOMY, seed_schedule_vii, seed_taxonomy, taxonomy_rows

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

TAG_COUNTS = {"sdg": 17, "population": 10, "scheme": 54, "lens": 4, "domain": 5, "theme": 11, "sub_theme": 48}


def load() -> tuple[dict, dict]:
    read = lambda name: json.loads((TAXONOMY / name).read_text(encoding="utf-8"))
    return read("themes.json"), read("common.json")


class TestTaxonomyRows:
    def test_counts(self):
        tags, links = taxonomy_rows(*load())
        assert Counter(t.kind for t in tags) == TAG_COUNTS
        assert len(links) == 211  # 85 + 4 lens SDG, 61 clause, 61 scheme

    def test_parents_come_before_children(self):
        tags, _ = taxonomy_rows(*load())
        seen: set[str] = set()
        for t in tags:
            assert t.parent is None or t.parent in seen, t.slug
            seen.add(t.slug)

    def test_tree_shape(self):
        tags, _ = taxonomy_rows(*load())
        kind = {t.slug: t.kind for t in tags}
        for t in tags:
            expected = {"theme": "domain", "sub_theme": "theme"}.get(t.kind)
            assert (kind[t.parent] if t.parent else None) == expected, t.slug

    def test_every_link_resolves(self):
        tags, links = taxonomy_rows(*load())
        slugs = {t.slug for t in tags}
        clauses = {f"clause:{c['code']}" for c in json.loads(DATA.read_text())["categories"]}
        assert {link.linked for link in links} <= slugs | clauses

    def test_one_link_per_clause_with_every_sector_in_the_note(self):
        _, links = taxonomy_rows(*load())
        wash = [link for link in links if link.tag == "sub_theme-wash" and link.linked.startswith("clause:")]
        assert [(link.linked, link.note) for link in wash] == [("clause:i", "Sanitation; Safe Drinking Water")]

    def test_unknown_sdg_raises(self):
        themes, common = load()
        themes["lenses"][0]["adds_sdgs"] = ["99"]
        with pytest.raises(ValueError, match="SDG '99'"):
            taxonomy_rows(themes, common)


@pytest.mark.integration
class TestSeedAgainstPostgres:
    """Runs inside one transaction that is rolled back, so the database is left as it was."""

    @pytest.fixture
    def cur(self):
        try:
            conn = psycopg.connect(DSN, connect_timeout=3)
        except psycopg.OperationalError:
            pytest.skip("compose Postgres not reachable on localhost:5433")
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT to_regclass('tag_links')")
            if cursor.fetchone()[0] is None:
                pytest.skip("tag_links missing: run make migrate")
            yield cursor
        finally:
            conn.rollback()
            conn.close()

    def test_seed_is_idempotent(self, cur):
        seed_schedule_vii(cur)
        first = seed_taxonomy(cur)
        assert seed_taxonomy(cur) == first
        cur.execute("SELECT kind, count(*) FROM tags WHERE kind = ANY(%s) GROUP BY 1", (list(TAG_COUNTS),))
        assert dict(cur.fetchall()) == TAG_COUNTS
        cur.execute(
            "SELECT k.kind, count(*) FROM tag_links l JOIN tags k ON k.id = l.linked_tag_id GROUP BY 1"
        )
        assert dict(cur.fetchall()) == {"sdg": 89, "csr_sector": 61, "scheme": 61}

    def test_a_dropped_tag_is_deprecated_not_deleted(self, cur):
        seed_schedule_vii(cur)
        seed_taxonomy(cur)
        cur.execute(
            "INSERT INTO tags (slug, label, kind, code) VALUES ('lens-gone', 'Gone', 'lens', 'gone')"
        )
        seed_taxonomy(cur)
        cur.execute("SELECT status FROM tags WHERE slug = 'lens-gone'")
        assert cur.fetchone()[0] == "deprecated"

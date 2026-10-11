"""Import's tags: the vocabulary, what a finding may carry, and what the writer puts in the tag tables."""

from __future__ import annotations

import json
import os
import pathlib

import psycopg
import pytest
from psycopg.rows import dict_row
from pydantic import ValidationError

from app.ingest import taxonomy
from app.ingest.records import ProgramRecord
from app.ingest.research_records import OrgIdentityFinding, ProgramFinding
from app.ingest.writer import write_tags

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")
SEED = next((p / "seed" / "data" / "taxonomy" for p in pathlib.Path(__file__).resolve().parents
             if (p / "seed" / "data" / "taxonomy").is_dir()), None)

SOURCE = {"evidence": "The programme federates women's self-help groups in Udalguri district.",
          "source_url": "https://example.org/programmes", "confidence": "high"}


def program(**kw) -> ProgramFinding:
    return ProgramFinding(name="SHG federation", **SOURCE, **kw)


class TestTheVocabulary:
    def test_it_is_the_seed_files(self):
        if SEED is None:
            pytest.skip("seed/ is not beside the tests")
        for name in ("themes.json", "common.json"):
            ours = json.loads((pathlib.Path(taxonomy.__file__).parent / "data" / name).read_text())
            assert ours == json.loads((SEED / name).read_text()), f"copy {name} from seed/data/taxonomy"

    def test_every_slug_the_writer_resolves_is_one_the_seed_writes(self):
        if SEED is None:
            pytest.skip("seed/ is not beside the tests")
        import sys
        sys.path.insert(0, str(SEED.parents[2]))
        from seed.taxonomy_seed import taxonomy_rows
        load = lambda name: json.loads((SEED / name).read_text())
        seeded = {t.slug for t in taxonomy_rows(load("themes.json"), load("common.json"))[0]}
        ours = {slug for codes in taxonomy.TAG_SLUGS.values() for slug in codes.values()}
        assert ours <= seeded, sorted(ours - seeded)

    def test_themes_and_sub_themes_share_one_namespace_without_collisions(self):
        assert len(taxonomy.THEME_CODES) == len(set(taxonomy.THEME_CODES))
        assert {"shg-empowerment", "institution-building", "disaster-preparedness"} <= set(taxonomy.THEME_CODES)

    def test_populations_and_lenses(self):
        assert "women" in taxonomy.POPULATION_CODES and "digital" in taxonomy.LENS_CODES


class TestAFindingsTags:
    def test_codes_from_the_taxonomy_with_a_note(self):
        f = program(themes=["institution-building", "institution-building"], populations=["women"],
                    tag_note="programme page: 'SHG federations of women'")
        assert f.themes == ["institution-building"] and f.populations == ["women"]

    def test_an_invented_code_is_kept_for_the_writer_to_drop_and_note(self):
        f = program(themes=[" Womens-Empowerment ", "fln"], tag_note="programme page")
        assert f.themes == ["womens-empowerment", "fln"]

    def test_the_schema_offers_the_codes(self):
        examples = ProgramFinding.model_json_schema()["properties"]["themes"]["items"]["examples"]
        assert "institution-building" in examples

    def test_a_tag_without_its_evidence_is_refused(self):
        with pytest.raises(ValidationError, match="tag_note"):
            program(lenses=["digital"])

    def test_at_most_three_themes(self):
        with pytest.raises(ValidationError):
            program(themes=["fln", "ecce", "ncd", "wash"], tag_note="annual report")

    def test_untagged_is_fine_and_the_org_carries_the_same_fields(self):
        assert program().themes == []
        org = OrgIdentityFinding(name="Test CSO", source_type="org_document", evidence_tier="claimed",
                                 themes=["disaster"], tag_note="about page: 'flood relief and preparedness'",
                                 **SOURCE)
        assert org.themes == ["disaster"]


@pytest.mark.integration
class TestWriteTags:
    """One rolled-back transaction against a migrated, taxonomy-seeded database."""

    @pytest.fixture
    async def conn(self):
        try:
            conn = await psycopg.AsyncConnection.connect(DSN, row_factory=dict_row, connect_timeout=3)
        except psycopg.OperationalError:
            pytest.skip("Postgres not reachable")
        try:
            if not (await (await conn.execute("SELECT 1 FROM tags WHERE kind = 'sub_theme' LIMIT 1")).fetchone()):
                pytest.skip("taxonomy not seeded")
            yield conn
        finally:
            await conn.rollback()
            await conn.close()

    async def test_codes_land_as_inferred_tags_and_a_rerun_adds_nothing(self, conn):
        org = (await (await conn.execute(
            "INSERT INTO orgs (name, slug) VALUES ('Tag Test CSO', 'tag-test-cso') RETURNING id")).fetchone())["id"]
        pid = (await (await conn.execute(
            "INSERT INTO programs (org_id, name) VALUES (%s, 'SHG federation') RETURNING id", (org,))).fetchone())["id"]
        rec = ProgramRecord(entity_name="Tag Test CSO", name="SHG federation", themes=["institution-building"],
                            populations=["women"], lenses=["no-such-lens"], tag_note="programme page",
                            source_type="org_document", evidence_tier="claimed", source_url="https://e.org",
                            source_name="t", fetched_at="2026-10-11T00:00:00Z")
        added, reasons = await write_tags(conn, "program_id", pid, rec)
        assert added == 2
        assert reasons == ["lens 'no-such-lens' is not a taxonomy code; dropped"]
        rows = await (await conn.execute(
            "SELECT t.slug, pt.is_inferred, pt.tagged_by, pt.note FROM program_tags pt JOIN tags t ON t.id = pt.tag_id "
            "WHERE pt.program_id = %s ORDER BY 1", (pid,))).fetchall()
        assert [r["slug"] for r in rows] == ["population-women", "sub_theme-institution-building"]
        assert all(r["is_inferred"] and r["tagged_by"] == "sangam-import" and r["note"] == "programme page"
                   for r in rows)
        assert (await write_tags(conn, "program_id", pid, rec))[0] == 0

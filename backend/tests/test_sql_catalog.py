"""The catalog is a security control, so these tests assert what it must NOT contain."""

from __future__ import annotations

import pytest

from app.agent.tools.sql import catalog as cat


class TestWithheld:
    """Each of these is a decision, not an oversight. Changing one is a policy change."""

    @pytest.mark.parametrize(
        "table",
        [
            "checkpoints",  # every user's conversation history, in this same database
            "checkpoint_blobs",
            "checkpoint_writes",
            "checkpoint_migrations",
            "users",  # account records; email is the only interesting column
            "threads",  # maps a person to their chat sessions
            "schema_migrations",
            "graph_ingest_log",
        ],
    )
    def test_table_is_not_readable(self, table):
        assert table not in cat.TABLE_NAMES
        assert table in cat.KNOWN_EXCLUDED, f"{table} is excluded but not declared as such"

    @pytest.mark.parametrize(
        "table,column,why",
        [
            ("contacts", "email", "personal email of an office bearer"),
            ("contacts", "phone", "personal phone of an office bearer"),
            ("chunks", "embedding", "1536 floats per row would destroy the context window"),
            ("chunks", "content_tsv", "machine-only, unreadable"),
            ("score_adjustments", "adjusted_by", "a staff member's uuid, unresolvable without users"),
        ],
    )
    def test_column_is_not_readable(self, table, column, why):
        assert table in cat.COLUMNS, f"{table} vanished from the catalog"
        assert column not in cat.COLUMNS[table], why

    def test_withheld_columns_also_absent_from_the_star_expansion(self):
        """SELECT * must not be a way around the column list."""
        assert "email" not in cat.STAR_COLUMNS["contacts"]
        assert "embedding" not in cat.STAR_COLUMNS["chunks"]


class TestDerivedIndexes:
    def test_star_expansion_drops_heavy_columns_only(self):
        heavy = {c.name for c in cat.CATALOG["orgs"].columns if c.heavy}
        assert heavy == {"contact", "sections", "profile"}
        assert set(cat.STAR_COLUMNS["orgs"]) == set(cat.COLUMNS["orgs"]) - heavy

    def test_heavy_columns_are_resolvable_but_not_starred(self):
        """qualify() needs the full schema so naming a heavy column works;
        STAR_COLUMNS is what gives `*` its narrower meaning."""
        assert "profile" in cat.COLUMNS["orgs"]
        assert "profile" in cat.SQLGLOT_SCHEMA["orgs"]
        assert "profile" not in cat.STAR_COLUMNS["orgs"]

    def test_sqlglot_schema_covers_every_table(self):
        assert set(cat.SQLGLOT_SCHEMA) == cat.TABLE_NAMES

    def test_primary_keys_carry_their_citation_kind(self):
        for table, kind in [("orgs", "org"), ("funders", "funder"),
                            ("funder_activity", "activity"), ("fit_scores", "score")]:
            assert cat.CITE_COLUMNS[(table, "id")] == kind

    def test_foreign_keys_inherit_the_kind_they_point_at(self):
        """This is what makes a programs or contacts row citable with no frontend change."""
        assert cat.CITE_COLUMNS[("programs", "org_id")] == "org"
        assert cat.CITE_COLUMNS[("contacts", "funder_id")] == "funder"
        assert cat.CITE_COLUMNS[("org_tags", "org_id")] == "org"
        assert cat.CITE_COLUMNS[("fit_score_items", "fit_score_id")] == "score"

    def test_citation_kinds_stay_within_the_frontend_union(self):
        """frontend/features/ask/lib/citations.ts must link every kind here, plus graph."""
        assert set(cat.CITE_COLUMNS.values()) <= {"org", "funder", "activity", "score"}


class TestDefects:
    """Defect strings are injected into results. They must stay specific enough to act on."""

    def test_the_verified_data_bugs_are_recorded(self):
        assert "news_mentions" in cat.DEFECTS
        assert "documents" in cat.DEFECTS

    def test_news_defect_says_zero_means_unlinked_not_absent(self):
        text = " ".join(cat.DEFECTS["news_mentions"]).lower()
        assert "never" in text and "no news exists" in text

    def test_the_locations_defect_went_when_the_data_was_fixed(self):
        # seed.py parented every district to Assam regardless of what Darpan
        # said, which made DIMAPUR a district of Assam. It now reads
        # state_of_registration, so the caveat would be a lie.
        # test_geography_is_parented_correctly proves it against real rows.
        assert "locations" not in cat.DEFECTS

    def test_every_defect_is_a_sentence_not_a_label(self):
        for table, defects in cat.DEFECTS.items():
            for d in defects:
                assert len(d) > 30 and d.endswith("."), f"{table}: {d!r} reads like a label"


def test_self_check_rejects_a_dangling_foreign_key():
    """The import-time guard must actually fire, or it is decoration."""
    import dataclasses

    broken = dataclasses.replace(
        cat.CATALOG["funder_activity"],
        foreign_keys=(cat.ForeignKey("partner_org_id", "nonexistent_table.id"),),
    )
    original = cat.CATALOG
    try:
        cat.CATALOG = {**original, "funder_activity": broken}
        cat.COLUMNS = {**cat.COLUMNS, "funder_activity": cat.COLUMNS["funder_activity"]}
        with pytest.raises(ValueError, match="not in the catalog"):
            cat._self_check()
    finally:
        cat.CATALOG = original

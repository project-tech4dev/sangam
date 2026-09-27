"""What the SQL validator must refuse, and what it must let through."""

from __future__ import annotations

import pytest
import sqlglot

from app.agent.tools.sql.validator import (
    HARD_MAX_ROWS,
    MAX_SQL_CHARS,
    SqlRejected,
    validate,
)


def reject(sql: str, *, max_rows: int = 50) -> str:
    with pytest.raises(SqlRejected) as excinfo:
        validate(sql, max_rows=max_rows)
    return str(excinfo.value)


class TestNotASelect:
    @pytest.mark.parametrize(
        "sql,expected",
        [
            ("DROP TABLE orgs", "only SELECT"),
            ("TRUNCATE TABLE orgs", "only SELECT"),
            ("CREATE TABLE x AS SELECT * FROM orgs", "only SELECT"),
            ("ALTER TABLE orgs ADD COLUMN x text", "only SELECT"),
            ("GRANT SELECT ON orgs TO bob", "only SELECT"),
            ("COPY orgs TO '/tmp/x.csv'", "only SELECT"),
            ("VACUUM", "only SELECT"),
            ("SET statement_timeout = 0", "only SELECT"),
            ("RESET ROLE", "only SELECT"),
            ("BEGIN", "only SELECT"),
        ],
    )
    def test_rejected(self, sql, expected):
        assert expected in reject(sql)


class TestWritesHidingInsideAQuery:
    """The root parses as a Query, so the positive type check alone is not enough."""

    @pytest.mark.parametrize(
        "sql",
        [
            "WITH x AS (DELETE FROM orgs RETURNING *) SELECT * FROM x",
            "WITH x AS (UPDATE orgs SET name='x' RETURNING id) SELECT id FROM x",
            "WITH x AS (INSERT INTO orgs (slug,name) VALUES ('a','b') RETURNING id) SELECT id FROM x",
        ],
    )
    def test_cte_write_is_rejected(self, sql):
        assert "writes or changes state" in reject(sql)

    def test_select_into_creates_a_table(self):
        assert "INTO" in reject("SELECT * INTO copy_of_orgs FROM orgs")

    def test_for_update_takes_locks(self):
        assert "locking" in reject("SELECT id FROM orgs FOR UPDATE")


class TestMultipleStatements:
    def test_two_statements(self):
        assert "2 statements" in reject("SELECT 1; DROP TABLE orgs")

    def test_smuggled_reset_role(self):
        """RESET ROLE would escape the reader role, so this path matters twice."""
        assert "exactly one SELECT" in reject("SELECT id FROM orgs; RESET ROLE")

    def test_comment_payload_never_survives(self):
        """Not a rejection: regeneration drops the comment entirely."""
        result = validate("SELECT id FROM orgs -- ; DROP TABLE orgs")
        assert "DROP" not in result.sql.upper()
        assert "--" not in result.sql


class TestTableAccess:
    @pytest.mark.parametrize(
        "table",
        ["checkpoints", "checkpoint_writes", "checkpoint_blobs", "users", "threads"],
    )
    def test_withheld_tables_are_unknown(self, table):
        assert "unknown table" in reject(f"SELECT * FROM {table}")

    def test_withheld_table_hidden_in_a_cte(self):
        assert "unknown table" in reject("WITH x AS (SELECT * FROM checkpoints) SELECT * FROM x")

    def test_withheld_table_in_a_union_arm(self):
        """The root is exp.Union, not exp.Select; the table scan must still reach it."""
        message = reject("SELECT id FROM orgs UNION ALL SELECT id FROM checkpoints")
        assert "unknown table" in message

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM information_schema.tables",
            "SELECT * FROM pg_catalog.pg_class",
            "SELECT * FROM other_schema.orgs",
        ],
    )
    def test_cross_schema_is_refused(self, sql):
        assert "cross-schema" in reject(sql)

    def test_unknown_table_suggests_near_misses(self):
        message = reject("SELECT * FROM org")
        assert "unknown table" in message and "orgs" in message

    def test_cte_may_not_shadow_a_real_table(self):
        message = reject("WITH orgs AS (SELECT 1 AS id) SELECT id FROM orgs")
        assert "shadows a real table" in message


class TestFunctions:
    @pytest.mark.parametrize(
        "sql,fragment",
        [
            ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
            ("SELECT pg_sleep(30)", "pg_sleep"),
            ("SELECT lo_import('/etc/passwd')", "lo_import"),
            ("SELECT pg_ls_dir('/')", "pg_ls_dir"),
        ],
    )
    def test_dangerous_functions_are_not_on_the_allowlist(self, sql, fragment):
        """All of these are valid single-statement SELECTs that succeed as superuser."""
        message = reject(sql)
        assert fragment in message and "not allowed" in message

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM dblink('a','b') AS t(x text)",
            "SELECT * FROM generate_series(1, 1000000)",
            "SELECT * FROM pg_read_file('/etc/passwd')",
        ],
    )
    def test_table_functions_in_from(self, sql):
        message = reject(sql)
        assert "table functions are not allowed" in message or "not allowed" in message

    def test_session_identity(self):
        assert "not allowed" in reject("SELECT current_user")

    def test_catalog_casts(self):
        assert "catalog types" in reject("SELECT 'orgs'::regclass")

    def test_placeholders_are_explained(self):
        message = reject("SELECT * FROM orgs WHERE id = $1")
        assert "placeholders" in message and "literal" in message

    def test_pg_trgm_similarity_is_allowed(self):
        result = validate("SELECT id, similarity(name, 'kabil') AS s FROM orgs")
        assert "SIMILARITY" in result.sql.upper()


class TestColumnAccess:
    @pytest.mark.parametrize(
        "sql,column",
        [
            ("SELECT email FROM contacts", "email"),
            ("SELECT phone FROM contacts", "phone"),
            ("SELECT embedding FROM chunks", "embedding"),
            ("SELECT adjusted_by FROM score_adjustments", "adjusted_by"),
        ],
    )
    def test_withheld_columns_do_not_resolve(self, sql, column):
        message = reject(sql)
        assert column in message
        assert "db_describe_table" in message, "the error must name the recovery step"

    def test_withheld_column_in_a_subquery(self):
        message = reject("SELECT (SELECT string_agg(email, ',') FROM contacts) FROM orgs")
        assert "email" in message

    def test_error_lists_the_columns_that_do_exist(self):
        message = reject("SELECT sector FROM orgs")
        assert "Columns of orgs" in message
        assert "legal_form" in message

    def test_sector_gets_a_pointed_hint(self):
        """The single most likely wrong guess against this schema."""
        assert "org_tags" in reject("SELECT sector FROM orgs")


class TestLimits:
    def test_absent_limit_is_injected(self):
        result = validate("SELECT id FROM orgs")
        assert result.limit == 50
        assert result.sql.endswith("LIMIT 51")  # +1 to detect truncation
        assert any("no LIMIT" in r for r in result.rewrites)

    def test_oversized_limit_is_clamped(self):
        result = validate("SELECT id FROM orgs LIMIT 100000")
        assert result.limit == 50
        assert any("clamped" in r for r in result.rewrites)

    def test_a_smaller_limit_is_intent_and_is_kept(self):
        result = validate("SELECT id FROM orgs LIMIT 5")
        assert result.limit == 5
        assert result.sql.endswith("LIMIT 6")

    def test_fetch_first_is_clamped_not_rejected(self):
        """M0 finding: FETCH occupies args['limit'], and Query.limit() replaces it."""
        result = validate("SELECT id FROM orgs FETCH FIRST 10000 ROWS ONLY")
        assert result.limit == 50
        assert "FETCH" not in result.sql.upper()

    def test_limit_applies_at_the_top_of_a_union(self):
        result = validate("SELECT id FROM orgs UNION SELECT id FROM funders")
        assert result.sql.rstrip().upper().endswith("LIMIT 51")

    def test_non_literal_limit(self):
        assert "integer literal" in reject("SELECT id FROM orgs LIMIT (SELECT 5)")

    def test_hard_cap_applies_even_when_asked_for_more(self):
        result = validate("SELECT id FROM orgs", max_rows=10_000)
        assert result.limit == HARD_MAX_ROWS


class TestResourceGuards:
    def test_oversized_sql(self):
        sql = "SELECT id FROM orgs WHERE name IN (" + ",".join(["'x'"] * 3000) + ")"
        assert len(sql) > MAX_SQL_CHARS
        assert "characters" in reject(sql)

    def test_deep_nesting_does_not_escape_as_recursionerror(self):
        sql = "(" * 3000 + "SELECT 1" + ")" * 3000
        assert reject(sql)  # a SqlRejected, not a RecursionError

    def test_recursive_cte_explains_the_alternative(self):
        message = reject(
            "WITH RECURSIVE t AS (SELECT id, parent_id FROM locations "
            "UNION ALL SELECT l.id, l.parent_id FROM locations l JOIN t ON t.parent_id = l.id) "
            "SELECT * FROM t"
        )
        assert "WITH RECURSIVE" in message and "parent_id" in message


class TestStarExpansion:
    def test_star_omits_heavy_columns(self):
        result = validate("SELECT * FROM orgs")
        for heavy in ("sections", "profile", "contact"):
            assert f'"{heavy}"' not in result.sql
        assert '"legal_form"' in result.sql

    def test_star_expansion_names_what_it_omitted(self):
        rewrites = validate("SELECT * FROM orgs").rewrites
        message = next(r for r in rewrites if "omitted" in r)
        for heavy in ("orgs.contact", "orgs.profile", "orgs.sections"):
            assert heavy in message, "the model cannot ask for a column it was not told about"

    def test_heavy_column_is_still_selectable_by_name(self):
        assert '"profile"' in validate("SELECT profile FROM orgs LIMIT 1").sql

    def test_count_star_is_not_an_expansion(self):
        result = validate("SELECT count(*) FROM grants")
        assert result.aggregate is True
        assert "COUNT(*)" in result.sql.upper()


class TestCitations:
    def test_primary_key_is_citable(self):
        plans = validate("SELECT o.id, o.name FROM orgs o").citations
        assert [(p.output_column, p.kind) for p in plans] == [("id", "org")]

    def test_foreign_key_inherits_the_kind(self):
        """Why programs/contacts/join tables are citable with no frontend change."""
        plans = validate("SELECT p.org_id, p.name FROM programs p").citations
        assert ("org_id", "org") in [(p.output_column, p.kind) for p in plans]

    def test_duplicate_output_names_are_disambiguated(self):
        """dict_row would otherwise keep only the last 'id' — silent data loss."""
        result = validate(
            "SELECT o.id, f.id FROM orgs o "
            "JOIN grants g ON g.org_id = o.id JOIN funders f ON f.id = g.funder_id"
        )
        names = [p.output_column for p in result.citations]
        assert len(names) == len(set(names)) == 2
        assert any("called 'id'" in r for r in result.rewrites)

    def test_aggregate_has_no_row_citations(self):
        assert validate("SELECT count(*) FROM grants").citations == ()


class TestRealQueriesStillParse:
    """The seven queries the curated tools already run, with placeholders made literal."""

    CORPUS = (
        """SELECT o.id, o.name, dl.name AS district, sl.name AS state
           FROM orgs o
           LEFT JOIN locations dl ON dl.id = o.registered_location_id
           LEFT JOIN locations sl ON sl.id = dl.parent_id
           WHERE o.name ILIKE '%' || 'kabil' || '%'
              OR similarity(o.name, 'kabil') > 0.3
           ORDER BY similarity(o.name, 'kabil') DESC NULLS LAST, o.name
           LIMIT 15""",
        """SELECT g.id, o.name AS org_name, g.title, g.status, g.start_date
           FROM grants g JOIN orgs o ON o.id = g.org_id
           WHERE g.funder_id = 1 ORDER BY g.start_date DESC NULLS LAST""",
        """SELECT fs.id, fs.total_score, o.name AS org_name, f.name AS funder_name, r.version
           FROM fit_scores fs
           JOIN orgs o ON o.id = fs.org_id
           JOIN funders f ON f.id = fs.funder_id
           JOIN rubrics r ON r.id = fs.rubric_id
           ORDER BY r.version, fs.total_score DESC""",
        """SELECT rc.code, rc.label, rc.points, fsi.score, fsi.justification
           FROM fit_score_items fsi
           JOIN rubric_criteria rc ON rc.id = fsi.criterion_id
           WHERE fsi.fit_score_id = 1 ORDER BY rc.code""",
    )

    @pytest.mark.parametrize("sql", CORPUS)
    def test_accepted_and_stable(self, sql):
        result = validate(sql)
        regenerated = sqlglot.parse_one(result.sql, dialect="postgres").sql(dialect="postgres")
        assert regenerated == result.sql

    def test_lateral_join_survives(self):
        result = validate(
            "SELECT o.id, t.sectors FROM orgs o "
            "LEFT JOIN LATERAL (SELECT array_agg(tg.label) AS sectors "
            "FROM org_tags ot JOIN tags tg ON tg.id = ot.tag_id WHERE ot.org_id = o.id) t ON true"
        )
        assert "LATERAL" in result.sql.upper()

    def test_percent_literals_survive_regeneration(self):
        assert "'%kabil%'" in validate("SELECT id FROM orgs WHERE name ILIKE '%kabil%'").sql


class TestUsefulQueriesTheCuratedToolsCannotAnswer:
    """The reason this feature exists at all."""

    @pytest.mark.parametrize(
        "sql",
        [
            ("SELECT f.name, count(g.id) AS n FROM funders f "
            "LEFT JOIN grants g ON g.funder_id = f.id GROUP BY f.name ORDER BY n DESC"),
            ("SELECT l.name, count(o.id) AS orgs FROM locations l "
            "JOIN orgs o ON o.registered_location_id = l.id GROUP BY l.name"),
            ("SELECT t.label, count(*) AS n FROM org_tags ot "
            "JOIN tags t ON t.id = ot.tag_id GROUP BY t.label ORDER BY n DESC LIMIT 10"),
            ("SELECT o.name, avg(fs.total_score) AS mean FROM orgs o "
            "JOIN fit_scores fs ON fs.org_id = o.id GROUP BY o.name HAVING avg(fs.total_score) > 20"),
        ],
    )
    def test_accepted(self, sql):
        result = validate(sql)
        assert result.aggregate is True
        assert result.sql

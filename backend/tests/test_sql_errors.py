"""What a failed query tells the model.

The retry loop is the agent's, so the only thing under our control is whether
the error string carries enough to converge. These tests use a fake exception —
no database — because the mapper duck-types .sqlstate and .diag.
"""

from __future__ import annotations

from app.agent.tools.sql.errors import FAILED_PREFIX, MAX_MESSAGE_CHARS, explain_db_error


class FakeDiag:
    def __init__(self, primary="", hint="", detail=""):
        self.message_primary = primary
        self.message_hint = hint
        self.message_detail = detail


class FakePgError(Exception):
    def __init__(self, sqlstate, primary="", hint="", detail=""):
        super().__init__(primary or sqlstate)
        self.sqlstate = sqlstate
        self.diag = FakeDiag(primary, hint, detail)


SQL = 'SELECT "o"."id" AS "id", "o"."setor" AS "setor" FROM "orgs" AS "o" LIMIT 51'


def test_undefined_column_lists_the_columns_that_exist():
    message = explain_db_error(
        FakePgError("42703", 'column o.setor does not exist',
                    hint='Perhaps you meant to reference the column "o.sector".'),
        executed_sql=SQL, tables=["orgs"],
    )
    assert "42703" in message
    assert "Columns of orgs" in message and "legal_form" in message
    assert "HINT" in message
    assert "Next:" in message


def test_every_failure_echoes_the_sql_that_actually_ran():
    """The model sent one string; the executor ran the regenerated one. Without
    the echo it diffs against text that never existed."""
    message = explain_db_error(FakePgError("42703", "boom"), executed_sql=SQL, tables=["orgs"])
    assert SQL in message


def test_timeout_suggests_narrowing_rather_than_retrying():
    message = explain_db_error(FakePgError("57014", "canceling statement due to statement timeout"),
                               executed_sql=SQL, tables=["orgs"])
    assert "time limit" in message
    assert "aggregate" in message.lower()


def test_grouping_error_mentions_the_citation_id_trap():
    """The id column added for citations is the usual cause of a 42803 here."""
    message = explain_db_error(FakePgError("42803", "column must appear in the GROUP BY clause"),
                               executed_sql=SQL, tables=["orgs"])
    assert "GROUP BY" in message and "min()" in message


def test_insufficient_privilege_does_not_blame_the_sql():
    """42501 means the reader role refused, not that the query is malformed."""
    message = explain_db_error(FakePgError("42501", "permission denied for table checkpoints"),
                               executed_sql=SQL, tables=[])
    assert "not readable by this tool" in message


class TestConnectionErrorsNeverLeakTheDsn:
    """psycopg puts host and user into OperationalError. That must not reach a
    model provider or a chat transcript."""

    class FakeOperationalError(Exception):
        sqlstate = None
        diag = None

    def test_dsn_is_not_in_the_message(self):
        exc = self.FakeOperationalError(
            'connection failed: host="db.prod.internal" user="sangam" password supplied'
        )
        exc.__class__.__name__ = "OperationalError"
        message = explain_db_error(exc, executed_sql=SQL, tables=["orgs"])
        for secret in ("db.prod.internal", "sangam", "password"):
            assert secret not in message
        assert "unreachable" in message
        assert "do not retry" in message

    def test_a_server_side_error_is_not_mistaken_for_a_connection_error(self):
        message = explain_db_error(FakePgError("42703", "no such column"),
                                   executed_sql=SQL, tables=["orgs"])
        assert "unreachable" not in message


def test_message_is_capped():
    message = explain_db_error(
        FakePgError("42703", "x" * 5000), executed_sql=SQL,
        tables=["orgs", "grants", "funders", "fit_scores"],
    )
    assert len(message) <= MAX_MESSAGE_CHARS


def test_prefix_is_stable_because_the_retry_limiter_counts_it():
    message = explain_db_error(FakePgError("42703", "x"), executed_sql=SQL, tables=[])
    assert message.startswith(FAILED_PREFIX)

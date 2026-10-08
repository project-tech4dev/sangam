"""Post-migration integrity checks against the live compose Postgres."""

import os

import psycopg
import pytest

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def conn():
    try:
        with psycopg.connect(DSN, connect_timeout=3) as connection:
            yield connection
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")


def test_preserved_row_counts(conn):
    # At least 96, not exactly: the importer adds a documents row per source it
    # reads. What this guards is that the restored research documents survive.
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] >= 96
    assert conn.execute("SELECT count(*) FROM graph_ingest_log").fetchone()[0] == 29


def test_seed_order_invariant(conn):
    rows = dict(conn.execute("SELECT slug, id FROM orgs ORDER BY id").fetchall())
    assert rows.get("kabil") == 9 and rows.get("bdf") == 10
    funders = dict(conn.execute("SELECT slug, id FROM funders ORDER BY id").fetchall())
    assert funders.get("axis-bank-foundation") == 1
    assert funders.get("tata-trusts") == 4


def test_documents_sequence_advanced(conn):
    next_id = conn.execute(
        "SELECT nextval(pg_get_serial_sequence('documents','id'))"
    ).fetchone()[0]
    conn.execute("SELECT setval(pg_get_serial_sequence('documents','id'), %s)", (next_id - 1,))
    assert next_id > 96


def test_v2_content_present(conn):
    assert conn.execute(
        "SELECT count(*) FROM funder_activity WHERE kind = 'partner' AND partner_org_id IS NOT NULL"
    ).fetchone()[0] == 4
    assert conn.execute("SELECT count(*) FROM programs").fetchone()[0] == 4
    assert conn.execute(
        "SELECT count(*) FROM org_identifiers WHERE id_type = 'fcra'"
    ).fetchone()[0] >= 1
    assert conn.execute("SELECT count(*) FROM contacts WHERE kind = 'office_bearer'").fetchone()[0] >= 50
    primary = conn.execute(
        """
        SELECT count(*) FROM org_tags ot
        JOIN orgs o ON o.id = ot.org_id
        WHERE o.slug = 'the-ant' AND ot.role = 'primary'
        """
    ).fetchone()[0]
    assert primary >= 1

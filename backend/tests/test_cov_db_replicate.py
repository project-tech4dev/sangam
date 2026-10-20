"""replicate: dependency order, the schema precondition, dry run and a full copy, over fake connections."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.db import replicate


def test_parents_come_before_children_and_self_references_are_fine():
    tables = ["grants", "orgs", "funders", "locations"]
    edges = [("grants", "orgs"), ("grants", "funders"), ("locations", "locations"), ("orgs", "locations"),
             ("grants", "not_copied")]
    assert replicate.ordered(tables, edges) == ["funders", "locations", "orgs", "grants"]


def test_a_cycle_stops_the_run():
    with pytest.raises(SystemExit, match="foreign-key cycle"):
        replicate.ordered(["a", "b"], [("a", "b"), ("b", "a")])


class Copy:
    def __init__(self, db, table, direction):
        self.db, self.table, self.direction = db, table, direction

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield from self.db.data[self.table]

    def write(self, data):
        self.db.data[self.table] = [data] if data else []


class FakeDB:
    """Rows are stored as COPY chunks; count is the number of chunks."""

    def __init__(self, shape, data, edges=(), serial=()):
        self.shape, self.data, self.edges, self.serial = shape, data, list(edges), set(serial)
        self.log: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextmanager
    def transaction(self):
        yield

    def cursor(self):
        db = self

        class Cursor:
            def copy(self, sql):
                table = sql.split('"')[1]
                db.log.append(sql)
                return Copy(db, table, "out" if "TO STDOUT" in sql else "in")

        return Cursor()

    def execute(self, sql, params=None):
        self.log.append(sql)
        rows: list = []
        if sql is replicate.COLUMNS_SQL:
            rows = [(t, c) for t, cols in self.shape.items() for c in cols]
        elif sql is replicate.TABLES_SQL:
            rows = [(t,) for t in sorted(self.shape) if t not in params[0]]
        elif sql is replicate.EDGES_SQL:
            rows = self.edges
        elif sql.startswith("SELECT count(*)"):
            rows = [(len(self.data.get(sql.split('"')[1], [])),)]
        elif sql.startswith("DELETE FROM"):
            self.data[sql.split('"')[1]] = []
        elif sql.startswith("SELECT a.attname"):
            rows = [("id", f"{params[0]}_id_seq")] if params[0] in self.serial else []

        class Result:
            def fetchall(self_inner):
                return rows

            def fetchone(self_inner):
                return rows[0]

        return Result()


SHAPE = {"orgs": ["id", "name"], "grants": ["id", "org_id"], "schema_migrations": ["version"]}


@pytest.fixture
def run(monkeypatch, capsys):
    def _run(source, target, *argv, env=None):
        env = env if env is not None else {"DATABASE_URL": "postgres://t", "REPLICATE_SOURCE_URL": "postgres://s"}
        for key in ("DATABASE_URL", "REPLICATE_SOURCE_URL"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr(replicate.sys, "argv", ["replicate", *argv])
        dbs = {"postgres://s": source, "postgres://t": target}
        monkeypatch.setattr(replicate.psycopg, "connect", lambda url: dbs[url])
        code = replicate.main()
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def _pair():
    source = FakeDB(SHAPE, {"orgs": [b"o1", b"o2"], "grants": [b"g1"]}, edges=[("grants", "orgs")],
                    serial={"orgs"})
    target = FakeDB(SHAPE, {"orgs": [b"old"], "grants": []}, serial={"orgs"})
    return source, target


def test_a_dry_run_writes_nothing(run):
    source, target = _pair()
    code, out, _ = run(source, target)
    assert code == 0 and "dry run" in out and "2 table(s), 3 row(s)" in out
    assert target.data["orgs"] == [b"old"] and not any(s.startswith("DELETE") for s in target.log)


def test_yes_replaces_children_first_and_resyncs_sequences(run, monkeypatch):
    source, target = _pair()

    def write(self, data):  # the binary stream arrives as one buffer; split it back into source rows
        self.db.data[self.table] = list(source.data[self.table])

    monkeypatch.setattr(Copy, "write", write)
    code, out, err = run(source, target, "--yes")
    assert code == 0, err
    deletes = [s for s in target.log if s.startswith("DELETE")]
    assert deletes == ['DELETE FROM "grants"', 'DELETE FROM "orgs"']
    assert target.data == {"orgs": [b"o1", b"o2"], "grants": [b"g1"]}
    assert any("setval" in s for s in target.log) and "every table matches" in out


def test_a_count_mismatch_after_copy_fails(run):
    source, target = _pair()
    code, _, err = run(source, target, "--yes")  # the fake writes one chunk per table, so orgs has 1 of 2
    assert code == 1 and "MISMATCH" in err and "orgs" in err


def test_only_limits_the_tables_and_rejects_unknown_ones(run):
    source, target = _pair()
    code, out, _ = run(source, target, "--only", "orgs")
    assert code == 0 and "1 table(s), 2 row(s)" in out
    with pytest.raises(SystemExit, match="not copyable: nope"):
        run(*_pair(), "--only", "orgs,nope")


def test_different_schemas_refuse(run):
    source, _ = _pair()
    target = FakeDB({"orgs": ["id"], "extra": ["id"]}, {})
    code, _, err = run(source, target)
    assert code == 1 and "schemas differ" in err
    assert "source only: grants, schema_migrations" in err and "target only: extra" in err
    assert "different columns: orgs" in err


@pytest.mark.parametrize("env, words", [
    ({"DATABASE_URL": "postgres://t"}, "set DATABASE_URL"),
    ({"DATABASE_URL": "postgres://t", "REPLICATE_SOURCE_URL": "postgres://t"}, "same database"),
])
def test_missing_or_identical_urls_refuse(run, env, words):
    code, _, err = run(None, None, env=env)
    assert code == 2 and words in err

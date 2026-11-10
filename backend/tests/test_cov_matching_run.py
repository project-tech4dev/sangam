"""make match: one org or every org, each saved with run_by NULL, and the pool always closed."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.matching import run as match_run

ORGS = [{"id": 1, "slug": "kabil"}, {"id": 2, "slug": "pratham"}]


class FakePool:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None
        self.opened = self.closed = False

    async def open(self):
        self.opened = True

    async def close(self):
        self.closed = True

    @asynccontextmanager
    async def connection(self):
        pool = self

        class Conn:
            async def execute(self, sql, params):
                pool.sql, pool.params = sql, params

                class Cur:
                    async def fetchall(self_inner):
                        return pool.rows

                return Cur()

        yield Conn()


@pytest.fixture
def harness(monkeypatch):
    saved: list[tuple] = []

    def install(rows):
        pool = FakePool(rows)
        monkeypatch.setattr(match_run, "make_pool", lambda url, max_size: pool)

        async def run_and_save(reader, writer, org_id, run_by):
            saved.append((org_id, run_by, reader is pool and writer is pool))
            return {"funders_checked": 12, "tiers": {"strong": 2}, "run_id": f"r{org_id}"}

        monkeypatch.setattr(match_run, "run_and_save", run_and_save)
        return pool

    return install, saved


async def test_every_org_is_matched(harness, capsys):
    install, saved = harness
    pool = install(ORGS)
    await match_run.main(None)
    assert saved == [(1, None, True), (2, None, True)]
    assert "WHERE" not in pool.sql and pool.opened and pool.closed
    assert "kabil: 12 funders, {'strong': 2} run r1" in capsys.readouterr().out


async def test_one_org_by_slug_or_id(harness):
    install, saved = harness
    pool = install(ORGS[:1])
    await match_run.main("kabil")
    assert "slug = %(v)s OR id::text = %(v)s" in pool.sql and pool.params == {"v": "kabil"}
    assert saved == [(1, None, True)]


async def test_an_unknown_org_exits_and_still_closes_the_pool(harness):
    install, saved = harness
    pool = install([])
    with pytest.raises(SystemExit, match="no org nobody"):
        await match_run.main("nobody")
    assert saved == [] and pool.closed

"""repo.save: the row lock and the write share one transaction, so parallel readers never drop each other's facts."""

from contextlib import asynccontextmanager

from app.proposals.work import Applied
from app.repositories import proposals as repo


class Conn:
    """Records each statement with whether a transaction was open when it ran."""

    def __init__(self):
        self.open, self.seen = False, []

    @asynccontextmanager
    async def transaction(self):
        self.open = True
        try:
            yield
        finally:
            self.open = False

    async def execute(self, sql, params=()):
        self.seen.append((sql.split()[0], self.open))
        row = {"work": {"facts": {}}, "title": "t"}

        class Cursor:
            async def fetchone(self):
                return row

        return Cursor()


class Pool:
    def __init__(self):
        self.conn = Conn()

    @asynccontextmanager
    async def connection(self):
        yield self.conn


async def test_the_lock_is_held_until_the_write():
    pool = Pool()
    await repo.save(pool, 6, lambda work, title: Applied(work=work, summary={}, title=None))
    assert pool.conn.seen == [("SELECT", True), ("UPDATE", True)]


async def test_a_missing_row_writes_nothing():
    pool = Pool()

    async def none():
        return None

    class Empty(Conn):
        async def execute(self, sql, params=()):
            self.seen.append((sql.split()[0], self.open))

            class Cursor:
                fetchone = staticmethod(none)

            return Cursor()

    pool.conn = Empty()
    assert await repo.save(pool, 6, lambda w, t: None) is None
    assert pool.conn.seen == [("SELECT", True)]

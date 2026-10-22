"""repo.save: the row lock and the write share one transaction, so parallel readers never drop each other's facts."""

import asyncio
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



class Counting(Pool):
    """Counts connections held at once."""

    def __init__(self):
        super().__init__()
        self.held = self.most = 0

    @asynccontextmanager
    async def connection(self):
        self.held += 1
        self.most = max(self.most, self.held)
        await asyncio.sleep(0.01)
        try:
            yield self.conn
        finally:
            self.held -= 1


def keep(work, title):
    return Applied(work=work, summary={}, title=None)


async def test_saves_to_one_proposal_queue_without_holding_a_connection():
    pool = Counting()
    await asyncio.gather(*(repo.save(pool, 6, keep) for _ in range(10)))
    assert pool.most == 1 and len(pool.conn.seen) == 20


async def test_two_proposals_save_side_by_side():
    pool = Counting()
    await asyncio.gather(repo.save(pool, 6, keep), repo.save(pool, 7, keep))
    assert pool.most == 2

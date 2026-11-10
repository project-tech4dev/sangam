from uuid import UUID

import pytest

from app.api.routes import threads
from app.core.security import ANONYMOUS
from tests.conftest import TEST_USER, make_app
from tests.test_access import as_caller, client

OTHER = UUID("99999999-8888-7777-6666-555555555555")


@pytest.fixture
def owners(monkeypatch):
    claimed = {"mine": TEST_USER, "theirs": OTHER}

    async def owner_of(pool, *, thread_id):
        return claimed.get(thread_id)

    monkeypatch.setattr("app.api.routes.threads.repo.owner_of", owner_of)


@pytest.mark.parametrize(("thread_id", "status"), [("mine", 204), ("new", 204), ("theirs", 404)])
async def test_owned_follows_the_post_rule(owners, thread_id, status):
    async with client(make_app(threads.router)) as c:
        response = await c.get(f"/api/threads/{thread_id}/owned")
    assert response.status_code == status


async def test_owned_signed_out_is_401(owners):
    app = as_caller(make_app(threads.router), ANONYMOUS)
    async with client(app) as c:
        response = await c.get("/api/threads/mine/owned")
    assert response.status_code == 401


class _Conn:
    def __init__(self, row):
        self.row, self.sql = row, None

    async def execute(self, sql, params):
        self.sql, self.params = sql, params
        return self

    async def fetchone(self):
        return self.row


class _Pool:
    def __init__(self, row):
        self.conn = _Conn(row)

    def connection(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


@pytest.mark.parametrize(("row", "owner"), [({"user_id": OTHER}, OTHER), (None, None)])
async def test_owner_of_reads_the_claim(row, owner):
    pool = _Pool(row)
    assert await threads.repo.owner_of(pool, thread_id="t1") == owner
    assert pool.conn.params == ("t1",)

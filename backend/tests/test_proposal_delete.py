"""repo.delete against the compose Postgres, as each caller: which proposal rows and draft files go, and which stay.

Everything runs in one transaction that is rolled back.
"""

import json
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.repositories import proposals as repo

DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")

pytestmark = pytest.mark.integration


class Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn


@pytest.fixture
async def db():
    try:
        conn = await psycopg.AsyncConnection.connect(DSN, connect_timeout=3, row_factory=dict_row)
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable on localhost:5433")
    async with conn, conn.transaction(force_rollback=True):
        yield conn, await _world(conn)


async def _world(conn) -> dict:
    """Org A with one person per role, proposal P with two saved versions, and three files P must not take."""

    async def one(sql, params=()):
        return (await (await conn.execute(sql, params)).fetchone())["id"]

    tag = uuid4().hex[:8]
    a = await one("INSERT INTO orgs (slug, name) VALUES (%s, 'A') RETURNING id", (f"del-a-{tag}",))
    b = await one("INSERT INTO orgs (slug, name) VALUES (%s, 'B') RETURNING id", (f"del-b-{tag}",))
    people = {}
    for name, org, role, staff in [("admin_a", a, "admin", False), ("steward_a", a, "steward", False),
                                   ("member_a", a, "member", False), ("admin_b", b, "admin", False),
                                   ("staff", None, None, True)]:
        auth_id = uuid4()
        user_id = await one("INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, %s) RETURNING id",
                            (f"{name}-{tag}@del.test", auth_id, staff))
        if org:
            await conn.execute("INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, %s)",
                               (user_id, org, role))
        people[name] = str(auth_id)

    p = await one("INSERT INTO proposals (org_id, title) VALUES (%s, 'P') RETURNING id", (a,))
    q = await one("INSERT INTO proposals (org_id, title) VALUES (%s, 'Q') RETURNING id", (a,))

    async def doc(path, doc_type="proposal_draft"):
        return await one("INSERT INTO documents (org_id, title, doc_type, storage_path, is_public) "
                         "VALUES (%s, 'd', %s, %s, false) RETURNING id", (a, doc_type, path))

    docs = {
        "v1": await doc(f"org-vault/{a}/proposals/{p}/v1.docx"),
        "v2": await doc(f"org-vault/{a}/proposals/{p}/v2.docx"),
        "theirs": await doc(f"org-vault/{a}/proposals/{q}/v1.docx"),
        "shared": await doc(f"org-vault/{a}/proposals/{p}/v3.docx"),
        "form": await doc(f"org-vault/{a}/form.pdf", "vault_upload"),
    }
    await conn.execute("UPDATE proposals SET draft_document_id = %s WHERE id = %s", (docs["shared"], q))
    versions = [{"n": n, "document_id": docs[k]} for n, k in enumerate(["v1", "v2", "theirs", "shared", "form"], 1)]
    await conn.execute("UPDATE proposals SET work = %s WHERE id = %s", (Jsonb({"versions": versions}), p))
    return {"a": a, "p": p, "q": q, "docs": docs, "people": people, "folder": f"org-vault/{a}/proposals/{p}/"}


async def _delete(conn, world, who, removes=True):
    removed = []

    async def remove_files(paths):
        removed.extend(paths)
        return removes

    await conn.execute("SELECT set_config('role', 'authenticated', true), set_config('request.jwt.claims', %s, true)",
                       (json.dumps({"sub": world["people"][who]}),))
    try:
        return await repo.delete(Pool(conn), world["p"], folder=world["folder"], remove_files=remove_files), removed
    finally:
        await conn.execute("RESET ROLE")


async def _left(conn, world) -> set[str]:
    rows = await (await conn.execute("SELECT id FROM documents WHERE id = ANY(%s)",
                                     (list(world["docs"].values()),))).fetchall()
    return {k for k, v in world["docs"].items() if v in {r["id"] for r in rows}}


async def _exists(conn, proposal_id) -> bool:
    return (await (await conn.execute("SELECT 1 FROM proposals WHERE id = %s", (proposal_id,))).fetchone()) is not None


@pytest.mark.parametrize("who", ["admin_a", "steward_a", "staff"])
async def test_a_proposal_takes_only_its_own_saved_versions(db, who):
    conn, world = db
    deleted, removed = await _delete(conn, world, who)
    assert deleted and removed == [f"{world['folder']}v1.docx", f"{world['folder']}v2.docx"]
    assert await _left(conn, world) == {"theirs", "shared", "form"}
    assert not await _exists(conn, world["p"]) and await _exists(conn, world["q"])


@pytest.mark.parametrize("who", ["member_a", "admin_b"])
async def test_anyone_else_deletes_nothing(db, who):
    conn, world = db
    deleted, removed = await _delete(conn, world, who)
    assert not deleted and removed == []
    assert await _exists(conn, world["p"]) and await _left(conn, world) == set(world["docs"])


async def test_a_file_storage_keeps_means_the_proposal_and_its_rows_stay(db):
    conn, world = db
    with pytest.raises(repo.FileNotRemoved):
        await _delete(conn, world, "admin_a", removes=False)
    assert await _exists(conn, world["p"]) and await _left(conn, world) == set(world["docs"])

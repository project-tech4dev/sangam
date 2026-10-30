"""Every deleted document is logged with its whole row, whoever deletes it and however."""

from __future__ import annotations

import pytest

from app.repositories import documents as repo
from tests.test_storage import _PoolOf

pytestmark = pytest.mark.integration


async def insert_doc(db) -> int:
    org = (await (await db.execute(
        "INSERT INTO orgs (slug, name) VALUES ('test-deleted-org', 'Test Deleted Org') RETURNING id"
    )).fetchone())["id"]
    row = await (await db.execute(
        """INSERT INTO documents (org_id, title, doc_type, storage_path, is_public, status)
           VALUES (%s, 'accounts', 'vault_upload', %s, false, 'received') RETURNING id""",
        (org, f"org-vault/{org}/abc-accounts.pdf"),
    )).fetchone()
    return row["id"]


async def logged(db, doc_id):
    return await (await db.execute(
        "SELECT id, org_id, old_row, restored_at FROM deleted_documents WHERE document_id = %s", (doc_id,)
    )).fetchone()


async def as_json(db, doc_id):
    row = await (await db.execute("SELECT to_jsonb(d) AS row FROM documents d WHERE id = %s", (doc_id,))).fetchone()
    return row and row["row"]


async def test_every_delete_is_logged_with_the_whole_row(db):
    doc = await insert_doc(db)
    before = await as_json(db, doc)
    await db.execute("DELETE FROM documents WHERE id = %s", (doc,))
    assert (await logged(db, doc))["old_row"] == before


async def test_a_refused_delete_logs_nothing(db):
    doc = await insert_doc(db)

    async def keep(path, org_id):
        return False

    with pytest.raises(repo.FileNotRemoved):
        await repo.delete_vault_upload(_PoolOf(db), document_id=doc, remove_file=keep)
    assert await logged(db, doc) is None

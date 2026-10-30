"""The Doc Vault routes: who may upload, and what a row is allowed to claim.

Bytes never reach the backend on the way in, so what these pin is the part
that is ours — the membership check before a signed URL is minted, and the
refusal to record a document that is not actually in storage.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import psycopg
import pytest

from app.api.routes import documents as documents_api
from app.core.config import Settings
from app.core.security import CurrentUser, get_principal
from app.repositories import documents as repo
from tests.conftest import TEST_USER, make_app

ROUTE = "app.api.routes.documents"
ROW = {
    "id": 7, "org_id": 3, "funder_id": None, "title": "Audited accounts FY2023-24",
    "doc_type": "vault_upload", "source_name": "vault upload", "source_url": None,
    "fetched_at": None,
}


@pytest.fixture
def storage_on(monkeypatch):
    monkeypatch.setattr(
        f"{ROUTE}.get_settings",
        lambda: Settings(supabase_url="https://p.supabase.co", supabase_service_key="svc"),
    )


def member(monkeypatch, org_id: int | None):
    async def fake(pool, *, org, user_id, write):
        return org_id

    monkeypatch.setattr(f"{ROUTE}.repo.org_id_for_member", fake)


class TestAskingForAnUploadUrl:
    async def test_a_member_gets_a_signed_url(self, client_for, monkeypatch, storage_on):
        member(monkeypatch, 3)

        async def fake_sign(bucket, key):
            assert bucket == "org-vault"
            assert key.startswith("3/"), "the key must lead with the org id — it is the RLS predicate"
            return "https://p.supabase.co/storage/v1/object/upload/sign/org-vault/3/x?token=t"

        monkeypatch.setattr(f"{ROUTE}.storage.signed_upload_url", fake_sign)
        async with client_for(documents_api.router) as client:
            response = await client.post(
                "/api/documents/uploads", json={"org": "kabil", "filename": "accounts.pdf"}
            )
        assert response.status_code == 200
        body = response.json()
        assert body["storage_path"].startswith("org-vault/3/")
        assert "token=t" in body["upload_url"]

    async def test_a_non_member_is_refused(self, client_for, monkeypatch, storage_on):
        member(monkeypatch, None)
        async with client_for(documents_api.router) as client:
            response = await client.post(
                "/api/documents/uploads", json={"org": "someone-else", "filename": "a.pdf"}
            )
        assert response.status_code == 403

    async def test_an_unknown_org_looks_the_same_as_a_refusal(self, client_for, monkeypatch, storage_on):
        """Which organisations exist is not something an outsider learns here."""
        member(monkeypatch, None)
        async with client_for(documents_api.router) as client:
            refused = await client.post(
                "/api/documents/uploads", json={"org": "not-a-real-org", "filename": "a.pdf"}
            )
        assert refused.status_code == 403

    async def test_503_when_storage_is_not_configured(self, client_for, monkeypatch):
        monkeypatch.setattr(f"{ROUTE}.get_settings", Settings)
        async with client_for(documents_api.router) as client:
            response = await client.post(
                "/api/documents/uploads", json={"org": "kabil", "filename": "a.pdf"}
            )
        assert response.status_code == 503


class TestRecordingAnUpload:
    def confirm(self, **over):
        return {"org": "kabil", "storage_path": "org-vault/3/abc-accounts.pdf", **over}

    async def test_writes_a_private_row_and_extracts_the_text(
        self, client_for, monkeypatch, storage_on
    ):
        member(monkeypatch, 3)
        monkeypatch.setattr(f"{ROUTE}.storage.stat", lambda b, k: _async({"name": "x"}))
        monkeypatch.setattr(f"{ROUTE}.storage.download", lambda b, k, max_bytes=0: _async(b"%PDF-"))
        captured = {}

        async def fake_insert(pool, **kwargs):
            captured.update(kwargs)
            return ROW

        monkeypatch.setattr(f"{ROUTE}.repo.insert_upload", fake_insert)
        async with client_for(documents_api.router) as client:
            response = await client.post("/api/documents", json=self.confirm(title="Accounts"))
        assert response.status_code == 201
        assert captured["org_id"] == 3
        assert captured["storage_path"] == "org-vault/3/abc-accounts.pdf"
        assert len(captured["content_hash"]) == 64, "hashed from the bytes we read back, not claimed"

    async def test_drops_nul_bytes_from_the_extracted_text(self, client_for, monkeypatch, storage_on):
        """Postgres text refuses 0x00; a PDF whose text carries one was a 500 the browser saw as "Failed to fetch"."""
        member(monkeypatch, 3)
        monkeypatch.setattr(f"{ROUTE}.storage.stat", lambda b, k: _async({"name": "x"}))
        monkeypatch.setattr(f"{ROUTE}.storage.download", lambda b, k, max_bytes=0: _async(b"%PDF-"))
        monkeypatch.setattr(f"{ROUTE}._extract", lambda data, key: ("Sec\x00tion 1", "h" * 64))
        captured = {}

        async def fake_insert(pool, **kwargs):
            captured.update(kwargs)
            return ROW

        monkeypatch.setattr(f"{ROUTE}.repo.insert_upload", fake_insert)
        async with client_for(documents_api.router) as client:
            response = await client.post("/api/documents", json=self.confirm())
        assert response.status_code == 201
        assert captured["content_md"] == "Section 1"

    async def test_refuses_a_key_in_another_orgs_folder(self, client_for, monkeypatch, storage_on):
        """The signed URL was minted for org 3; a row must not claim org 9's file."""
        member(monkeypatch, 3)
        async with client_for(documents_api.router) as client:
            response = await client.post(
                "/api/documents", json=self.confirm(storage_path="org-vault/9/abc-x.pdf")
            )
        assert response.status_code == 403

    async def test_refuses_a_key_in_the_archive_bucket(self, client_for, monkeypatch, storage_on):
        member(monkeypatch, 3)
        async with client_for(documents_api.router) as client:
            response = await client.post(
                "/api/documents", json=self.confirm(storage_path="source-archive/ab/cd-x.pdf")
            )
        assert response.status_code == 400

    async def test_refuses_when_nothing_was_actually_uploaded(
        self, client_for, monkeypatch, storage_on
    ):
        """A row pointing at a missing object is worse than no row."""
        member(monkeypatch, 3)
        monkeypatch.setattr(f"{ROUTE}.storage.stat", lambda b, k: _async(None))
        async with client_for(documents_api.router) as client:
            response = await client.post("/api/documents", json=self.confirm())
        assert response.status_code == 404


class TestDownloading:
    async def test_a_readable_document_gets_a_link(self, client_for, monkeypatch, storage_on):
        async def fake_row(pool, *, document_id, user_id):
            return {"id": 7, "title": "x", "storage_path": "org-vault/3/abc-x.pdf",
                    "is_public": False, "org_id": 3}

        monkeypatch.setattr(f"{ROUTE}.repo.readable_document", fake_row)
        monkeypatch.setattr(
            f"{ROUTE}.storage.signed_url", lambda b, k: _async(f"https://p/{b}/{k}?token=t")
        )
        async with client_for(documents_api.router) as client:
            response = await client.get("/api/documents/7/file")
        assert response.status_code == 200
        assert response.json()["url"].endswith("?token=t")

    async def test_someone_elses_private_document_is_a_404_not_a_403(
        self, client_for, monkeypatch, storage_on
    ):
        """Whether a private document exists is itself private."""
        async def fake_row(pool, *, document_id, user_id):
            return None

        monkeypatch.setattr(f"{ROUTE}.repo.readable_document", fake_row)
        async with client_for(documents_api.router) as client:
            response = await client.get("/api/documents/7/file")
        assert response.status_code == 404

    async def test_a_document_with_no_file_is_a_404(self, client_for, monkeypatch, storage_on):
        async def fake_row(pool, *, document_id, user_id):
            return {"id": 7, "title": "x", "storage_path": None, "is_public": True, "org_id": None}

        monkeypatch.setattr(f"{ROUTE}.repo.readable_document", fake_row)
        async with client_for(documents_api.router) as client:
            response = await client.get("/api/documents/7/file")
        assert response.status_code == 404


async def _async(value):
    return value


class TestDeletingAnUpload:
    def deleter(self, monkeypatch, outcome):
        removed: list[tuple[str, list[str]]] = []

        async def fake_remove(bucket, keys):
            removed.append((bucket, keys))
            return True

        async def fake_delete(pool, *, document_id, remove_file):
            if isinstance(outcome, Exception):
                raise outcome
            if outcome:
                assert await remove_file("org-vault/3/abc-accounts.pdf", 3)
            return outcome

        monkeypatch.setattr(f"{ROUTE}.storage.trash", fake_remove)
        monkeypatch.setattr(f"{ROUTE}.repo.delete_vault_upload", fake_delete)
        return removed

    async def test_staff_delete_the_row_and_the_file(self, client_for, monkeypatch, storage_on):
        removed = self.deleter(monkeypatch, True)
        async with client_for(documents_api.router) as client:
            response = await client.delete("/api/documents/7")
        assert response.status_code == 204
        assert removed == [("org-vault", ["3/abc-accounts.pdf"])]

    async def test_non_staff_are_refused(self, monkeypatch, storage_on):
        self.deleter(monkeypatch, True)
        app = make_app(documents_api.router)
        app.dependency_overrides[get_principal] = lambda: CurrentUser(id=TEST_USER, is_staff=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete("/api/documents/7")
        assert response.status_code == 403

    async def test_a_referenced_document_is_a_409(self, client_for, monkeypatch, storage_on):
        self.deleter(monkeypatch, repo.DocumentInUse(7))
        async with client_for(documents_api.router) as client:
            response = await client.delete("/api/documents/7")
        assert response.status_code == 409

    async def test_a_file_storage_would_not_delete_is_a_502(self, client_for, monkeypatch, storage_on):
        self.deleter(monkeypatch, repo.FileNotRemoved(7))
        async with client_for(documents_api.router) as client:
            response = await client.delete("/api/documents/7")
        assert response.status_code == 502

    async def test_a_row_left_after_its_file_went_is_a_500(self, client_for, monkeypatch, storage_on):
        self.deleter(monkeypatch, repo.RowNotRemoved(7))
        async with client_for(documents_api.router) as client:
            response = await client.delete("/api/documents/7")
        assert response.status_code == 500
        assert "delete it again" in response.json()["detail"]

    async def test_anything_but_a_vault_upload_is_a_404(self, client_for, monkeypatch, storage_on):
        self.deleter(monkeypatch, False)
        async with client_for(documents_api.router) as client:
            response = await client.delete("/api/documents/7")
        assert response.status_code == 404

    async def test_a_path_outside_the_vault_is_never_removed(self, monkeypatch):
        called = []
        monkeypatch.setattr(f"{ROUTE}.storage.trash", lambda b, k: called.append(b) or _async(True))
        assert await documents_api._remove_vault_file("source-archive/ab/r.pdf", 3) is False
        assert await documents_api._remove_vault_file("org-vault/../x", 3) is False
        assert called == []

    async def test_a_file_in_another_organisations_folder_is_never_removed(self, monkeypatch):
        """#329: a row can point into someone else's folder; deleting it must not take their file."""
        called = []
        monkeypatch.setattr(f"{ROUTE}.storage.trash", lambda b, k: called.append(k) or _async(True))
        assert await documents_api._remove_vault_file("org-vault/5/abc-theirs.pdf", 3) is False
        assert await documents_api._remove_vault_file("org-vault/33/abc-theirs.pdf", 3) is False
        assert called == []
        assert await documents_api._remove_vault_file("org-vault/3/abc-ours.pdf", 3) is True
        assert called == [["3/abc-ours.pdf"]]


# --- the membership SQL, against a real Postgres ---------------------------
# The unit tests above monkeypatch org_id_for_member, so the predicate that
# actually decides who may upload is only proved here.

STEWARD = UUID("00000000-0000-0000-0000-0000000000a1")
MEMBER = UUID("00000000-0000-0000-0000-0000000000a2")
OUTSIDER = UUID("00000000-0000-0000-0000-0000000000a3")


class _PoolOf:
    """One connection dressed as a pool, so a repository can be called inside
    a transaction the test rolls back."""

    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        @asynccontextmanager
        async def held():
            yield self._conn

        return held()


@pytest.fixture
async def org(db):
    """A throwaway org with three users in three relationships to it."""
    row = await (await db.execute(
        "INSERT INTO orgs (slug, name) VALUES ('test-vault-org', 'Test Vault Org') RETURNING id"
    )).fetchone()
    org_id = row["id"]
    for user, email in ((STEWARD, "s@t.invalid"), (MEMBER, "m@t.invalid"), (OUTSIDER, "o@t.invalid")):
        await db.execute(
            "INSERT INTO users (id, email, is_staff) VALUES (%s, %s, false)", (user, email)
        )
    await db.execute(
        "INSERT INTO org_members (user_id, org_id, role) VALUES (%s, %s, 'steward'), (%s, %s, 'member')",
        (STEWARD, org_id, MEMBER, org_id),
    )
    return org_id


@pytest.mark.integration
class TestWhoMayTouchAnOrgsVault:
    async def member(self, db, user, *, write, org="test-vault-org"):
        return await repo.org_id_for_member(_PoolOf(db), org=org, user_id=user, write=write)

    async def test_a_member_may_read_and_write(self, db, org):
        assert await self.member(db, MEMBER, write=False) == org
        assert await self.member(db, MEMBER, write=True) == org

    async def test_a_steward_may_read_and_not_write(self, db, org):
        """0004 defines a steward as an ecosystem player who reads an org's
        private data and cannot write. This is where that is true or not.
        """
        assert await self.member(db, STEWARD, write=False) == org
        assert await self.member(db, STEWARD, write=True) is None

    async def test_an_outsider_gets_nothing(self, db, org):
        assert await self.member(db, OUTSIDER, write=False) is None
        assert await self.member(db, OUTSIDER, write=True) is None

    async def test_staff_may_write_without_membership(self, db, org):
        await db.execute("UPDATE users SET is_staff = true WHERE id = %s", (OUTSIDER,))
        assert await self.member(db, OUTSIDER, write=True) == org

    async def test_resolves_by_id_as_well_as_slug(self, db, org):
        assert await self.member(db, MEMBER, write=True, org=str(org)) == org

    async def test_an_org_that_does_not_exist_is_None(self, db, org):
        assert await self.member(db, MEMBER, write=True, org="no-such-org") is None


@pytest.mark.integration
class TestDeleteVaultUpload:
    async def upload(self, db, org, **over):
        values = {"doc_type": "vault_upload", "is_public": False, **over}
        row = await (await db.execute(
            """INSERT INTO documents (org_id, title, doc_type, storage_path, is_public, status)
               VALUES (%s, 'accounts', %s, %s, %s, 'received') RETURNING id""",
            (org, values["doc_type"], f"org-vault/{org}/abc-accounts.pdf", values["is_public"]),
        )).fetchone()
        return row["id"]

    async def exists(self, db, doc_id):
        return (await (await db.execute("SELECT 1 FROM documents WHERE id = %s", (doc_id,))).fetchone()) is not None

    async def delete(self, db, doc_id, *, removed=True):
        calls = self.calls = []  # kept on the test, so a delete that raises can still be checked

        async def remove_file(path, org_id):
            calls.append(path)
            return removed

        result = await repo.delete_vault_upload(_PoolOf(db), document_id=doc_id, remove_file=remove_file)
        return result, calls

    async def test_the_row_and_the_file_go_together(self, db, org):
        doc_id = await self.upload(db, org)
        assert await self.delete(db, doc_id) == (True, [f"org-vault/{org}/abc-accounts.pdf"])
        assert not await self.exists(db, doc_id)

    async def test_the_row_stays_when_the_file_does_not_go(self, db, org):
        doc_id = await self.upload(db, org)
        with pytest.raises(repo.FileNotRemoved):
            await self.delete(db, doc_id, removed=False)
        assert await self.exists(db, doc_id)

    async def test_a_document_with_chunks_is_refused_before_the_file_goes(self, db, org):
        doc_id = await self.upload(db, org)
        await db.execute("INSERT INTO chunks (document_id, chunk_index, content) VALUES (%s, 0, 'x')", (doc_id,))
        touched = []

        async def remove_file(path, org_id):
            touched.append(path)
            return True

        with pytest.raises(repo.DocumentInUse):
            await repo.delete_vault_upload(_PoolOf(db), document_id=doc_id, remove_file=remove_file)
        assert touched == [], "a refused delete deletes nothing"
        assert await self.exists(db, doc_id)

    async def test_a_proposals_draft_is_refused_before_the_file_goes(self, db, org):
        doc_id = await self.upload(db, org)
        await db.execute(
            "INSERT INTO proposals (org_id, title, draft_document_id) VALUES (%s, 't', %s)", (org, doc_id))
        touched = []

        async def remove_file(path, org_id):
            touched.append(path)
            return True

        with pytest.raises(repo.DocumentInUse):
            await repo.delete_vault_upload(_PoolOf(db), document_id=doc_id, remove_file=remove_file)
        assert touched == [], "the draft keeps its file"
        assert await self.exists(db, doc_id)

    @pytest.mark.parametrize("column", ["template_id", "budget_document_id"])
    async def test_a_document_a_proposal_uses_is_refused_with_its_row_and_file_kept(self, db, org, column):
        """The row's DELETE runs first, so any foreign key refuses it before the file is touched."""
        doc_id = await self.upload(db, org)
        await db.execute(f"INSERT INTO proposals (org_id, title, {column}) VALUES (%s, 't', %s)", (org, doc_id))
        with pytest.raises(repo.DocumentInUse):
            await self.delete(db, doc_id)
        assert self.calls == [], "the file is never touched"
        assert await self.exists(db, doc_id)

    async def test_only_a_private_vault_upload_is_deleted(self, db, org):
        doc_id = await self.upload(db, org, doc_type="annual_report")
        assert await self.delete(db, doc_id) == (False, [])
        assert await self.exists(db, doc_id)

    async def test_a_row_pointing_into_another_organisations_folder_leaves_that_file_alone(
        self, db, org, monkeypatch
    ):
        """#329, end to end: the route's own remover refuses, nothing reaches storage, the row is kept."""
        row = await (await db.execute(
            """INSERT INTO documents (org_id, title, doc_type, storage_path, is_public, status)
               VALUES (%s, 'theirs', 'vault_upload', %s, false, 'received') RETURNING id""",
            (org, f"org-vault/{org + 1000}/abc-theirs.pdf"),
        )).fetchone()
        removed = []

        async def remove(bucket, keys):
            removed.append(keys)
            return True

        monkeypatch.setattr(f"{ROUTE}.storage.trash", remove)
        with pytest.raises(repo.FileNotRemoved):
            await repo.delete_vault_upload(_PoolOf(db), document_id=row["id"],
                                           remove_file=documents_api._remove_vault_file)
        assert removed == []
        assert await self.exists(db, row["id"])


class _FakePool:
    """A caller's connection: the row reads back, the DELETE removes `rowcount` rows, and the commit may fail."""

    def __init__(self, rowcount: int, commit_fails: bool = False):
        self.rowcount = rowcount
        self.commit_fails = commit_fails

    def connection(self):
        pool = self

        class _Cursor:
            rowcount = pool.rowcount

            async def fetchone(self):
                return {"storage_path": "org-vault/3/abc-accounts.pdf", "org_id": 3, "used": False}

        class _Conn:
            async def execute(self, sql, params=None):
                return _Cursor()

            @asynccontextmanager
            async def transaction(self):
                yield
                if pool.commit_fails:
                    raise psycopg.OperationalError("server closed the connection unexpectedly")

        @asynccontextmanager
        async def held():
            yield _Conn()

        return held()


async def test_a_delete_rls_quietly_refuses_touches_no_file():
    removed = []

    async def remove_file(path, org_id):
        removed.append(path)
        return True

    assert await repo.delete_vault_upload(_FakePool(rowcount=0), document_id=7, remove_file=remove_file) is False
    assert removed == []


async def test_a_commit_that_fails_after_the_file_went_is_reported(caplog):
    async def remove_file(path, org_id):
        return True

    with pytest.raises(repo.RowNotRemoved):
        await repo.delete_vault_upload(_FakePool(rowcount=1, commit_fails=True), document_id=7, remove_file=remove_file)
    assert "org-vault/3/abc-accounts.pdf" in caplog.text, "the log names the file that is gone"

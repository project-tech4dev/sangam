"""The Doc Vault routes: who may upload, and what a row is allowed to claim.

Bytes never reach the backend on the way in, so what these pin is the part
that is ours — the membership check before a signed URL is minted, and the
refusal to record a document that is not actually in storage.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

import pytest

from app.api.routes import documents as documents_api
from app.core.config import Settings
from app.repositories import documents as repo

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

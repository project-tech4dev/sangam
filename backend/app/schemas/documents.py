from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ReadModel


class DocumentOut(ReadModel):
    # Metadata only — content_md is deliberately not exposed over the list API.
    id: int
    org_id: int | None = None
    funder_id: int | None = None
    title: str | None = None
    doc_type: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None
    is_public: bool | None = None


# --- the Doc Vault ---------------------------------------------------------
# Bytes never pass through here. The browser asks for a signed URL, uploads
# straight to Storage, then tells us it landed — see docs/features/
# 2026-09-30-supabase-storage.md for why (a Vercel Function caps its request
# body well below the size of an annual report).


class UploadUrlIn(BaseModel):
    org: str = Field(description="org slug or id; the caller must be a member")
    filename: str = Field(min_length=1, max_length=200)


class UploadUrlOut(BaseModel):
    upload_url: str
    storage_path: str = Field(description="pass this back to POST /api/documents")
    expires_in_seconds: int


class UploadConfirmIn(BaseModel):
    org: str
    storage_path: str
    title: str | None = Field(default=None, max_length=300)
    doc_type: str = Field(default="vault_upload", max_length=60)


class FileLinkOut(BaseModel):
    url: str
    expires_in_seconds: int

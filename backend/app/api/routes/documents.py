from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import PageParams
from app.core.config import get_settings
from app.core.security import get_current_user, require_staff, require_user
from app.db.pool import PoolDep
from app.integrations import storage
from app.repositories import documents as repo
from app.schemas.common import Page
from app.schemas.documents import (
    DocumentOut,
    FileLinkOut,
    UploadConfirmIn,
    UploadUrlIn,
    UploadUrlOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=Page[DocumentOut], summary="Document metadata (the vault)")
async def list_documents(
    pool: PoolDep,
    page: PageParams = Depends(),
    org: str | None = None,
    funder: str | None = None,
    doc_type: str | None = None,
    user_id: UUID = Depends(get_current_user),
) -> Page[DocumentOut]:
    rows, total = await repo.list_documents(pool, limit=page.limit, offset=page.offset,
                                            org=org, funder=funder, doc_type=doc_type, user_id=user_id)
    return Page(items=[DocumentOut.model_validate(r) for r in rows],
                total=total, limit=page.limit, offset=page.offset)


# --- the Doc Vault ---------------------------------------------------------
# Three calls, none of which carries the file: ask for a URL, upload straight
# to Storage, say it landed. Authorisation is ours at every step — a signed URL
# is minted only after the membership check, and it is short-lived.
#
# They live on the documents router rather than under /orgs so the resource
# keeps its three-file set in one place; the org arrives in the body, which is
# where a create's owner belongs.

EXTRACT_LIMIT_BYTES = 20 * 1024 * 1024


def _require_storage() -> None:
    if not get_settings().storage_enabled:
        raise HTTPException(503, "document storage is not configured on this deployment")


@router.post("/uploads", response_model=UploadUrlOut, summary="Ask for a URL to upload to")
async def create_upload_url(
    body: UploadUrlIn,
    pool: PoolDep,
    user_id: UUID = Depends(require_user),
) -> UploadUrlOut:
    _require_storage()
    org_id = await repo.org_id_for_member(pool, org=body.org, user_id=user_id, write=False)
    if org_id is None:
        # Deliberately the same answer for "no such org" and "not your org":
        # which organisations exist is not something an outsider learns here.
        raise HTTPException(403, f"not a member of org {body.org!r}")
    key = storage.vault_key(org_id, body.filename)
    url = await storage.signed_upload_url(storage.ORG_VAULT, key)
    if url is None:
        raise HTTPException(502, "could not reach document storage")
    return UploadUrlOut(
        upload_url=url,
        storage_path=storage.qualify(storage.ORG_VAULT, key),
        expires_in_seconds=storage.UPLOAD_URL_TTL_SECONDS,
    )


@router.post("", response_model=DocumentOut, status_code=201, summary="Record an upload")
async def confirm_upload(
    body: UploadConfirmIn,
    pool: PoolDep,
    user_id: UUID = Depends(require_user),
) -> DocumentOut:
    _require_storage()
    org_id = await repo.org_id_for_member(pool, org=body.org, user_id=user_id, write=False)
    if org_id is None:
        raise HTTPException(403, f"not a member of org {body.org!r}")

    parts = storage.split(body.storage_path)
    if parts is None or parts[0] != storage.ORG_VAULT:
        raise HTTPException(400, "storage_path is not a vault key")
    bucket, key = parts
    # The key names its own org, and it was minted for this caller's org. A
    # row is not allowed to claim a file sitting in someone else's folder.
    if key.partition("/")[0] != str(org_id):
        raise HTTPException(403, "storage_path belongs to a different organisation")
    if await storage.stat(bucket, key) is None:
        raise HTTPException(404, "no object at that storage_path — did the upload finish?")

    # Read it back to extract the text and hash it. This is also the only
    # honest way to fill content_hash: the browser held the bytes, so anything
    # it told us about them would be a claim rather than a measurement.
    data = await storage.download(bucket, key, max_bytes=EXTRACT_LIMIT_BYTES)
    content_md, content_hash = _extract(data, key)
    if content_md:
        content_md = content_md.replace("\x00", "") or None  # some PDFs' text carries NULs, which Postgres refuses

    row = await repo.insert_upload(
        pool, org_id=org_id, uploaded_by=user_id, title=body.title, doc_type=body.doc_type,
        storage_path=body.storage_path, content_hash=content_hash, content_md=content_md,
    )
    return DocumentOut.model_validate(row)


def _extract(data: bytes | None, key: str) -> tuple[str | None, str | None]:
    """(text, sha256) from the uploaded bytes. Both None when it could not be
    read — the row is still worth having, and status stays 'received'.
    """
    if data is None:
        logger.warning("uploaded object %s could not be read back; stored without text", key)
        return None, None
    digest = storage.content_hash(data)
    name = key.lower()
    if name.endswith((".docx", ".xlsx")):
        from app.ingest import office

        try:
            text = "\n\n".join(office.docx_paragraphs(data)) if name.endswith(".docx") else office.xlsx_markdown(data)
        except Exception as exc:  # noqa: BLE001 - a damaged file raises many types
            logger.warning("no text from %s (%s: %s)", key, type(exc).__name__, exc)
            return None, digest
        return (text or None), digest
    if not name.endswith(".pdf"):
        return None, digest
    from app.agent.tools.files import extract_pdf_text  # agent-tool module; only an upload needs it

    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        try:
            text, _ = extract_pdf_text(Path(handle.name))
        except Exception as exc:  # noqa: BLE001 - pypdf raises many types
            logger.warning("no text from %s (%s: %s)", key, type(exc).__name__, exc)
            return None, digest
    return (text or None), digest


@router.get("/{document_id}/file", response_model=FileLinkOut, summary="A link to the file")
async def document_file(
    document_id: int,
    pool: PoolDep,
    user_id: UUID = Depends(get_current_user),
) -> FileLinkOut:
    _require_storage()
    row = await repo.readable_document(pool, document_id=document_id, user_id=user_id)
    # One 404 for "no such document" and "not yours": whether a private
    # document exists is itself private.
    if row is None or not row["storage_path"]:
        raise HTTPException(404, f"document {document_id} has no readable file")
    parts = storage.split(row["storage_path"])
    if parts is None:
        raise HTTPException(404, f"document {document_id} has no readable file")
    # Only the upload script writes staff-sources paths, always on a private, org-less row.
    if parts[0] == storage.STAFF_SOURCES and (row["is_public"] or row["org_id"] is not None):
        raise HTTPException(404, f"document {document_id} has no readable file")
    url = await storage.signed_url(*parts)
    if url is None:
        raise HTTPException(502, "could not reach document storage")
    return FileLinkOut(url=url, expires_in_seconds=storage.SIGNED_URL_TTL_SECONDS)


async def _remove_vault_file(storage_path: str, org_id: int) -> bool:
    parts = storage.split(storage_path)
    if parts is None or parts[0] != storage.ORG_VAULT:
        logger.warning("not removing %s: not a vault key", storage_path)
        return False
    if parts[1].partition("/")[0] != str(org_id):
        logger.warning("not removing %s: not in organisation %s's folder", storage_path, org_id)
        return False
    return await storage.remove(parts[0], [parts[1]])


@router.delete("/{document_id}", status_code=204, summary="Delete a Doc Vault upload and its file (staff)",
               dependencies=[Depends(require_staff)])
async def delete_document(document_id: int, pool: PoolDep) -> None:
    _require_storage()
    try:
        deleted = await repo.delete_vault_upload(pool, document_id=document_id, remove_file=_remove_vault_file)
    except repo.DocumentInUse:
        raise HTTPException(409, f"document {document_id} is still referenced; unlink it first") from None
    except repo.FileNotRemoved:
        raise HTTPException(502, f"could not delete the file for document {document_id}; the row is kept") from None
    except repo.RowNotRemoved:
        raise HTTPException(500, f"the file for document {document_id} was deleted but its row was not; "
                                 "delete it again to finish") from None
    if not deleted:
        raise HTTPException(404, f"no Doc Vault upload {document_id}")

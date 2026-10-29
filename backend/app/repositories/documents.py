from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


async def list_documents(pool: AsyncConnectionPool, *, limit: int, offset: int,
                         org: str | None = None, funder: str | None = None,
                         doc_type: str | None = None, user_id: object = None) -> tuple[list[dict], int]:
    """Public documents, plus the private ones of the caller's own orgs; staff see all."""
    sql = """
    SELECT d.id, d.org_id, d.funder_id, d.title, d.doc_type,
           d.source_name, d.source_url, d.fetched_at, d.is_public,
           COALESCE(d.storage_path, '') <> '' AS has_file,
           COUNT(*) OVER () AS total
    FROM documents d
    LEFT JOIN orgs o ON o.id = d.org_id
    LEFT JOIN funders f ON f.id = d.funder_id
    WHERE (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)
      AND (d.is_public
           OR EXISTS (SELECT 1 FROM org_members m WHERE m.org_id = d.org_id AND m.user_id = %(user)s)
           OR EXISTS (SELECT 1 FROM users u WHERE u.id = %(user)s AND u.is_staff))
    ORDER BY d.title NULLS LAST
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "org": org, "funder": funder, "doc_type": doc_type,
              "user": user_id}
    async with pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return rows, (rows[0]["total"] if rows else 0)


# The Doc Vault. Membership is checked here rather than in the route because
# it is the same question for every vault operation, and answering it in SQL
# keeps it one round trip.

_MEMBER_SQL = """
SELECT o.id
FROM orgs o
WHERE (o.slug = %(org)s OR o.id::text = %(org)s)
  AND (
    EXISTS (
      SELECT 1 FROM org_members m
      WHERE m.org_id = o.id AND m.user_id = %(user)s
        AND (%(write)s = false OR m.role IN ('admin', 'member'))
    )
    OR EXISTS (SELECT 1 FROM users u WHERE u.id = %(user)s AND u.is_staff)
  )
"""


async def org_id_for_member(
    pool: AsyncConnectionPool, *, org: str, user_id, write: bool
) -> int | None:
    """The org's id if this user may act on it, else None.

    `write=True` excludes stewards. Doc Vault uploads pass `write=False`: a steward adds the files a
    proposal draws on (0048). Staff pass either way.
    """
    async with pool.connection() as conn:
        row = await (
            await conn.execute(_MEMBER_SQL, {"org": org, "user": user_id, "write": write})
        ).fetchone()
    return row["id"] if row else None


async def insert_upload(
    pool: AsyncConnectionPool, *, org_id: int, uploaded_by, title: str | None,
    doc_type: str, storage_path: str, content_hash: str | None, content_md: str | None,
) -> dict:
    """A vault document: private, received, and owned by the uploader."""
    sql = """
    INSERT INTO documents (org_id, title, doc_type, source_name, storage_path,
                           content_hash, content_md, uploaded_by, fetched_at,
                           is_public, status)
    VALUES (%(org_id)s, %(title)s, %(doc_type)s, 'vault upload', %(storage_path)s,
            %(content_hash)s, %(content_md)s, %(uploaded_by)s, now(),
            false, 'received')
    RETURNING id, org_id, funder_id, title, doc_type, source_name, source_url, fetched_at,
              storage_path <> '' AS has_file
    """
    async with pool.connection() as conn:
        row = await (await conn.execute(sql, {
            "org_id": org_id, "title": title, "doc_type": doc_type,
            "storage_path": storage_path, "content_hash": content_hash,
            "content_md": content_md, "uploaded_by": uploaded_by,
        })).fetchone()
    return row


async def readable_document(pool: AsyncConnectionPool, *, document_id: int, user_id) -> dict | None:
    """A document with its storage_path, if this user may read it.

    A public document is readable by anyone signed in — it is a public report
    we archived. A private one needs membership of the owning org, or staff.
    """
    sql = """
    SELECT d.id, d.title, d.storage_path, d.is_public, d.org_id
    FROM documents d
    WHERE d.id = %(id)s
      AND (
        d.is_public
        OR EXISTS (
          SELECT 1 FROM org_members m
          WHERE m.org_id = d.org_id AND m.user_id = %(user)s
        )
        OR EXISTS (SELECT 1 FROM users u WHERE u.id = %(user)s AND u.is_staff)
      )
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql, {"id": document_id, "user": user_id})).fetchone()


async def upsert_source_dataset(
    pool: AsyncConnectionPool, *, title: str, source_key: str, storage_path: str, source_url: str,
    content_hash: str, extractor_version: str = "upload_staff_source/1",
) -> tuple[int, str]:
    """A staff dataset's row: private, nobody's, no content. Keyed on storage_path, so re-upload updates it."""
    params = {"title": title, "url": source_url, "key": source_key, "hash": content_hash, "path": storage_path,
              "version": extractor_version}
    async with pool.connection() as conn, conn.transaction():
        row = await (await conn.execute(
            """UPDATE documents SET content_hash = %(hash)s, fetched_at = now(), title = %(title)s,
                      source_url = %(url)s, source_name = %(key)s, extractor_version = %(version)s
               WHERE doc_type = 'source_dataset' AND storage_path = %(path)s RETURNING id""",
            params,
        )).fetchone()
        if row:
            return row["id"], "replaced"
        row = await (await conn.execute(
            """INSERT INTO documents (org_id, funder_id, title, doc_type, source_url, source_name,
                                      fetched_at, content_hash, extractor_version, storage_path,
                                      is_public, status)
               VALUES (NULL, NULL, %(title)s, 'source_dataset', %(url)s, %(key)s, now(), %(hash)s,
                       %(version)s, %(path)s, false, 'received')
               RETURNING id""",
            params,
        )).fetchone()
    return row["id"], "added"


async def list_source_datasets(pool: AsyncConnectionPool, ids: list[int] | None = None) -> list[dict]:
    """Staff dataset rows, all or just `ids`. Staff-only by construction: private and org-less."""
    sql = """
    SELECT id, title, source_name, source_url, storage_path, content_hash FROM documents
    WHERE doc_type = 'source_dataset' AND NOT is_public AND org_id IS NULL AND funder_id IS NULL
      AND (%(ids)s::bigint[] IS NULL OR id = ANY(%(ids)s::bigint[]))
    ORDER BY source_name, id
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql, {"ids": ids})).fetchall()


async def org_document_ids(pool: AsyncConnectionPool, org_id: int, ids: list[int]) -> set[int]:
    """Which of `ids` are this org's own documents."""
    if not ids:
        return set()
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT id FROM documents WHERE id = ANY(%s) AND org_id = %s", (ids, org_id))).fetchall()
    return {r["id"] for r in rows}


class DocumentInUse(Exception):
    """Something still references the document, so deleting it would break or silently take that too."""


class FileNotRemoved(Exception):
    """Storage did not delete the file, so the row was kept."""


class RowNotRemoved(Exception):
    """The file is gone but the row could not be deleted; deleting again finishes it."""



_CASCADING_SQL = """
SELECT EXISTS (SELECT 1 FROM chunks WHERE document_id = %(id)s)
    OR EXISTS (SELECT 1 FROM extraction_log WHERE document_id = %(id)s)
    OR EXISTS (SELECT 1 FROM document_links WHERE document_id = %(id)s)
    OR EXISTS (SELECT 1 FROM proposals WHERE draft_document_id = %(id)s) AS used
"""


async def delete_vault_upload(
    pool: AsyncConnectionPool, *, document_id: int, remove_file: Callable[[str, int], Awaitable[bool]],
) -> bool:
    """Delete a vault upload's file, then its row. False when there is no such vault upload.

    File first: a row left behind can be deleted again, a file with no row is never found.
    """
    file_removed = False
    try:
        async with pool.connection() as conn, conn.transaction():
            row = await (await conn.execute(
                """SELECT storage_path, org_id FROM documents
                   WHERE id = %(id)s AND doc_type = 'vault_upload' AND NOT is_public AND org_id IS NOT NULL""",
                {"id": document_id},
            )).fetchone()
            if row is None:
                return False
            if (await (await conn.execute(_CASCADING_SQL, {"id": document_id})).fetchone())["used"]:
                raise DocumentInUse(document_id)
            if row["storage_path"] and not await remove_file(row["storage_path"], row["org_id"]):
                raise FileNotRemoved(document_id)
            file_removed = True
            deleted = await conn.execute("DELETE FROM documents WHERE id = %(id)s", {"id": document_id})
            if deleted.rowcount != 1:
                raise RowNotRemoved(document_id)
    except Exception as exc:
        if not file_removed:
            raise
        logger.error("document %s: file %s removed but the row was not (%s: %s)",
                     document_id, row["storage_path"], type(exc).__name__, exc)
        raise RowNotRemoved(document_id) from exc
    return True

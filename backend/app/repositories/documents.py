from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


async def list_documents(pool: AsyncConnectionPool, *, limit: int, offset: int,
                         org: str | None = None, funder: str | None = None,
                         doc_type: str | None = None) -> tuple[list[dict], int]:
    sql = """
    SELECT d.id, d.org_id, d.funder_id, d.title, d.doc_type,
           d.source_name, d.source_url, d.fetched_at,
           COUNT(*) OVER () AS total
    FROM documents d
    LEFT JOIN orgs o ON o.id = d.org_id
    LEFT JOIN funders f ON f.id = d.funder_id
    WHERE (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
      AND (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)
    ORDER BY d.title NULLS LAST
    LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {"limit": limit, "offset": offset, "org": org, "funder": funder, "doc_type": doc_type}
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

    `write=True` excludes stewards: 0004 defines a steward as someone who reads
    an org's private data and cannot write. Staff pass either way.
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
    RETURNING id, org_id, funder_id, title, doc_type, source_name, source_url, fetched_at
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

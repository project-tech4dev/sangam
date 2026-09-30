"""Supabase Storage: the provenance archive, and the org Doc Vault.

The only module that talks to Storage. Optional, like the graph and Langfuse:
with SUPABASE_URL or SUPABASE_SERVICE_KEY unset every call is a no-op that logs
once, and research, promotion and the API carry on unchanged.

Nothing here raises. A Storage outage must not abort a research run or a
promotion — callers treat a None as "not archived" and write a null column.

The service-role key bypasses row-level security entirely, which is why it
stays server-side and the browser is only ever handed a short-lived signed URL.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.agent.tools.files import _safe_name
from app.core.config import get_settings

logger = logging.getLogger(__name__)

SOURCE_ARCHIVE = "source-archive"
ORG_VAULT = "org-vault"

# The bucket's own ceiling, from 0020_storage_buckets.sql. Checked before the
# upload so a 55 MB report fails here with a readable line rather than as an
# opaque rejection after the bytes have gone over the wire.
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
TIMEOUT_SECONDS = 120
SIGNED_URL_TTL_SECONDS = 600
# Supabase fixes this one: a signed upload URL is valid for two hours.
UPLOAD_URL_TTL_SECONDS = 7200

_warned = False


def _disabled() -> bool:
    """True when Storage is off. Says so once, not once per document."""
    global _warned
    if get_settings().storage_enabled:
        return False
    if not _warned:
        _warned = True
        logger.info(
            "Supabase Storage disabled (SUPABASE_URL / SUPABASE_SERVICE_KEY unset): "
            "documents are not archived and storage_path stays null"
        )
    return True


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    key = settings.supabase_service_key
    return httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/") + "/storage/v1",
        headers={"Authorization": f"Bearer {key}", "apikey": key},
        timeout=TIMEOUT_SECONDS,
    )


def qualify(bucket: str, key: str) -> str:
    """What goes in `documents.storage_path`: the bucket and the key together.

    One column has to say which of the two buckets an object is in, and
    inferring it from `is_public` would be a guess that happens to be right
    today. `<bucket>/<key>` is self-describing.
    """
    return f"{bucket}/{key}"


def split(storage_path: str) -> tuple[str, str] | None:
    """`documents.storage_path` back into (bucket, key). None if it is neither
    of ours — a path we did not write is not one we will hand out a URL for.
    """
    bucket, _, key = storage_path.partition("/")
    return (bucket, key) if key and bucket in (SOURCE_ARCHIVE, ORG_VAULT) else None


def url_prefix(source_url: str) -> str:
    """The folder a source URL's archived versions live under.

    Derived from the URL rather than the entity because `fetch_document` runs
    during research, and a funder_id does not exist until `resolve_funder` runs
    at promotion. The entity link lives in `documents.funder_id`, not the path.
    """
    return hashlib.sha256(source_url.encode()).hexdigest()[:12]


def archive_key(source_url: str, data: bytes, filename: str | None = None) -> str:
    """`<url-hash>/<content-sha256>-<name>` — URL for the folder, content for the file.

    Both halves earn their place. The URL hash means two sources both called
    `report.pdf` stop overwriting each other, which they do on disk today. The
    content hash means a funder republishing at the same URL next year adds a
    version instead of replacing the bytes a finding was read from - the exact
    provenance failure this archive exists to prevent.

    The content half is the full digest, not a prefix, because promotion reads
    it straight back out of the key into `documents.content_hash`, and every
    other content_hash in the catalog is a full sha256 (see `_provenance`). A
    long key is a fair price for a column that means the same thing everywhere.
    """
    name = _safe_name(filename or source_url.split("?")[0].rstrip("/").rsplit("/", 1)[-1])
    return f"{url_prefix(source_url)}/{content_hash(data)}-{name}"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_from_key(key: str) -> str | None:
    """The content sha256 out of a key built by `archive_key`, or None.

    None matters: a key written by any other route has no hash to report, and
    guessing one would put a wrong value in a provenance column.
    """
    head = Path(key).name.split("-", 1)[0]
    return head if len(head) == 64 and all(c in "0123456789abcdef" for c in head) else None


def _is_duplicate(response: httpx.Response) -> bool:
    """Whether a rejected upload was rejected for already being there.

    Measured against the live API, not assumed: Supabase answers a duplicate
    with **HTTP 400** and `{"statusCode":"409","error":"Duplicate",
    "code":"KeyAlreadyExists"}` in the body. Matching on the transport status
    alone logged every re-fetch of a document as an archiving failure.
    """
    if response.status_code not in (400, 409):
        return False
    try:
        body = response.json()
    except ValueError:
        return response.status_code == 409
    return (
        str(body.get("statusCode")) == "409"
        or body.get("error") == "Duplicate"
        or body.get("code") == "KeyAlreadyExists"
    )


async def upload(bucket: str, key: str, data: bytes, content_type: str) -> str | None:
    """Store bytes and return the key, or None if it did not happen.

    `x-upsert: false`, so re-archiving content already there is a duplicate
    rather than an overwrite — and a duplicate counts as success, because the
    object is present either way and the key is content-addressed.
    """
    if _disabled():
        return None
    if len(data) > MAX_ARCHIVE_BYTES:
        logger.warning(
            "not archiving %s: %.1f MB exceeds the %d MB bucket limit",
            key, len(data) / 1024 / 1024, MAX_ARCHIVE_BYTES // 1024 // 1024,
        )
        return None
    try:
        async with _client() as client:
            response = await client.post(
                f"/object/{bucket}/{key}",
                content=data,
                headers={"Content-Type": content_type or "application/octet-stream",
                         "x-upsert": "false"},
            )
        if _is_duplicate(response):
            return key
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("archiving %s/%s failed (%s: %s)", bucket, key, type(exc).__name__, exc)
        return None
    return key


async def list_prefix(bucket: str, prefix: str, limit: int = 20) -> list[dict[str, Any]]:
    """Objects under a folder, newest first. Empty on any failure."""
    if _disabled():
        return []
    try:
        async with _client() as client:
            response = await client.post(
                f"/object/list/{bucket}",
                json={"prefix": prefix, "limit": limit,
                      "sortBy": {"column": "created_at", "order": "desc"}},
            )
        response.raise_for_status()
        found = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("listing %s/%s failed (%s: %s)", bucket, prefix, type(exc).__name__, exc)
        return []
    return found if isinstance(found, list) else []


async def archived_key(bucket: str, source_url: str) -> str | None:
    """The newest archived version of a source URL, or None.

    Newest rather than the one a given finding was read from: research and
    promotion run minutes apart, so in practice they are the same object. A
    document re-archived between the two would resolve to the newer version.
    """
    prefix = url_prefix(source_url)
    objects = await list_prefix(bucket, prefix, limit=1)
    if not objects:
        return None
    name = objects[0].get("name")
    return f"{prefix}/{name}" if name else None


async def signed_url(bucket: str, key: str, ttl: int = SIGNED_URL_TTL_SECONDS) -> str | None:
    """A time-limited URL for a private object. None if it could not be made."""
    if _disabled():
        return None
    try:
        async with _client() as client:
            response = await client.post(f"/object/sign/{bucket}/{key}", json={"expiresIn": ttl})
        response.raise_for_status()
        path = response.json().get("signedURL")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("signing %s/%s failed (%s: %s)", bucket, key, type(exc).__name__, exc)
        return None
    if not path:
        return None
    return get_settings().supabase_url.rstrip("/") + "/storage/v1" + path


def vault_key(org_id: int, filename: str) -> str:
    """`<org_id>/<uuid4>-<name>` for the Doc Vault.

    Deliberately NOT content-addressed like `archive_key`, because of who holds
    the bytes. The archive is written by the server, which can hash what it
    just downloaded. A vault upload goes browser → Storage through a signed
    URL, so at the moment the key is minted the backend has never seen the
    file; a content hash there could only be one the client asserted, and a
    provenance column filled from an unverified claim is worse than an empty
    one. `documents.content_hash` is computed server-side afterwards, from the
    bytes we read back to extract the text.

    `<org_id>` first because that is what the RLS policy reads as
    `(storage.foldername(name))[1]::bigint`.
    """
    return f"{org_id}/{uuid.uuid4().hex}-{_safe_name(filename)}"


async def signed_upload_url(bucket: str, key: str) -> str | None:
    """A one-shot URL the browser can PUT to, valid two hours.

    This is what keeps file bytes out of the backend: Vercel Functions cap a
    request body at a few MB and an annual report is routinely larger. The
    authorisation decision still happens here — the URL is only minted for a
    caller who passed the membership check.
    """
    if _disabled():
        return None
    try:
        async with _client() as client:
            response = await client.post(f"/object/upload/sign/{bucket}/{key}")
        response.raise_for_status()
        path = response.json().get("url")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("signing upload %s/%s failed (%s: %s)", bucket, key, type(exc).__name__, exc)
        return None
    if not path:
        return None
    return get_settings().supabase_url.rstrip("/") + "/storage/v1" + path


async def download(bucket: str, key: str, max_bytes: int = MAX_ARCHIVE_BYTES) -> bytes | None:
    """Read an object back. None on anything that goes wrong, including a body
    larger than `max_bytes` — extraction reads this into memory.
    """
    if _disabled():
        return None
    try:
        async with _client() as client:
            response = await client.get(f"/object/{bucket}/{key}")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("reading %s/%s failed (%s: %s)", bucket, key, type(exc).__name__, exc)
        return None
    if len(response.content) > max_bytes:
        logger.warning("not reading %s/%s: %d bytes", bucket, key, len(response.content))
        return None
    return response.content


async def stat(bucket: str, key: str) -> dict[str, Any] | None:
    """The object's own record of itself, or None if it is not there.

    Used to confirm an upload actually landed before a documents row claims it
    did — the browser reporting success is not evidence, and a row pointing at
    a missing object is worse than no row.
    """
    prefix, _, name = key.rpartition("/")
    for entry in await list_prefix(bucket, prefix, limit=100):
        if entry.get("name") == name:
            return entry
    return None

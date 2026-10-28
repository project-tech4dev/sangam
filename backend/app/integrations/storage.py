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
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SOURCE_ARCHIVE = "source-archive"
ORG_VAULT = "org-vault"
# Staff-only workbooks, uploaded by scripts/upload_staff_source.py or the dashboard; 0032 creates it at 100 MB.
STAFF_SOURCES = "staff-sources"
STAFF_SOURCES_MAX_BYTES = 100 * 1024 * 1024
BUCKETS: tuple[str, ...] = (SOURCE_ARCHIVE, ORG_VAULT, STAFF_SOURCES)

# The bucket's own ceiling, from 0020_storage_buckets.sql. Checked before the
# upload so a 55 MB report fails here with a readable line rather than as an
# opaque rejection after the bytes have gone over the wire.
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
TIMEOUT_SECONDS = 120
SIGNED_URL_TTL_SECONDS = 600
# Supabase fixes this one: a signed upload URL is valid for two hours.
UPLOAD_URL_TTL_SECONDS = 7200
# A brief is linked from a rendered page, so the link has to outlive the visit.
BRIEF_URL_TTL_SECONDS = 3600

_warned = False


def _safe_name(name: str) -> str:
    # Strip any directory components and shell-unfriendly characters so the
    # agent can never write outside the downloads folder.
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name[:120] or "download"


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
    """`documents.storage_path` back into (bucket, key). None if it is not one
    of ours — a path we did not write is not one we will hand out a URL for.
    """
    bucket, _, key = storage_path.partition("/")
    # Dot and empty segments are normalised away by the HTTP client, so they could cross buckets.
    if not key or bucket not in BUCKETS or any(seg in ("", ".", "..") for seg in key.split("/")):
        return None
    return bucket, key


def url_prefix(source_url: str) -> str:
    """The folder a source URL's archived versions live under.

    Derived from the URL rather than the entity because `fetch_document` runs
    during research, and a funder_id does not exist until `resolve_funder` runs
    at promotion. The entity link lives in `documents.funder_id`, not the path.
    """
    return hashlib.sha256(source_url.encode()).hexdigest()[:12]


def archive_key(source_url: str, data: bytes, filename: str | None = None) -> str:
    """The key an object gets at FETCH time, when we do not yet know whose it is.

    `<url-hash>/<content-sha256>-<name>` — URL for the folder, content for the file.

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
    guessing one would put a wrong value in a provenance column. Read it before
    `catalog_key` renames the object — the readable name does not carry it.
    """
    head = Path(key).name.split("-", 1)[0]
    return head if len(head) == 64 and all(c in "0123456789abcdef" for c in head) else None


def filename_from_key(key: str) -> str:
    """The publisher's own filename, with any content hash stripped off."""
    name = Path(key).name
    return name.split("-", 1)[1] if hash_from_key(key) else name


def _year(as_of: str | None) -> str:
    """`FY2023-24` -> `2023-24`. Empty when the source did not say."""
    if not as_of:
        return ""
    digits = re.sub(r"[^0-9-]", "", as_of).strip("-")
    return digits if re.fullmatch(r"\d{4}(-\d{2,4})?", digits or "") else ""


def catalog_key(
    entity_slug: str, as_of: str | None, filename: str, suffix: str = "",
    prefix: str = "funders",
) -> str:
    """The key an object gets once PROMOTION knows which entity it belongs to.

    `<funders|orgs>/<slug>/<year>-<publisher's filename>`, which is browsable,
    sorts by year within an entity, and keeps the name the publisher itself
    used so a row can be matched back to its source by eye.

    The year and the funder both come from the catalog, so this cannot be built
    at fetch time — `fetch_document` runs during research and `resolve_funder`
    does not run until promotion. Hence two keys and a move between them, and
    hence a useful signal: anything left under a hash folder was fetched and
    never cited by a finding.

    `suffix` disambiguates the rare collision — same funder, same year, same
    published filename, different bytes.
    """
    stem, dot, ext = _safe_name(filename).rpartition(".")
    base = f"{stem}{'-' + suffix if suffix else ''}{dot}{ext}" if dot else (
        f"{_safe_name(filename)}{'-' + suffix if suffix else ''}"
    )
    year = _year(as_of)
    return f"{prefix}/{_safe_name(entity_slug)}/{year + '-' if year else ''}{base}"


def brief_key(slug: str) -> str:
    """Where an entity's rendered research brief lives.

    Alongside the sources rather than in a bucket of its own: same access rule
    — any signed-in user may read it — and a bucket is a boundary between
    access rules, not a filing cabinet.

    Unlike the two keys above this one is an identity, not a digest. It is the
    same key every time the brief is regenerated, which is why `render_docs`
    uploads it with `replace=True`.
    """
    return f"entities/{_safe_name(slug)}.md"


class BriefUnreachable(Exception):
    """A brief is published but no signed link could be made for it."""


async def brief_link(slug: str) -> str | None:
    """A signed link to an entity's published research brief; None when storage is off or none is published."""
    if _disabled():
        return None
    key = brief_key(slug)
    if await stat(SOURCE_ARCHIVE, key) is None:
        return None
    url = await signed_url(SOURCE_ARCHIVE, key, BRIEF_URL_TTL_SECONDS)
    if url is None:
        raise BriefUnreachable(slug)
    return url


async def move(bucket: str, source: str, destination: str) -> bool:
    """Rename an object in place. False on any failure, never raises.

    A failed move is not a failed promotion: the object is still archived under
    its fetch-time key, and the caller records whichever key is real.
    """
    if _disabled():
        return False
    try:
        async with _client() as client:
            response = await client.post(
                "/object/move",
                json={"bucketId": bucket, "sourceKey": source, "destinationKey": destination},
            )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "moving %s/%s to %s failed (%s: %s)", bucket, source, destination,
            type(exc).__name__, exc,
        )
        return False
    return True


async def remove(bucket: str, keys: list[str]) -> bool:
    """Delete objects. True once Storage accepts it (a key already gone counts); False on any failure."""
    if _disabled():
        return False
    try:
        async with _client() as client:
            response = await client.request("DELETE", f"/object/{bucket}", json={"prefixes": keys})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("removing %s from %s failed (%s: %s)", keys, bucket, type(exc).__name__, exc)
        return False
    return True


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


async def upload(
    bucket: str, key: str, data: bytes, content_type: str, *, replace: bool = False,
    max_bytes: int = MAX_ARCHIVE_BYTES,
) -> str | None:
    """Store bytes and return the key, or None if it did not happen.

    Defaults to no overwrite, so re-archiving content already there is a
    duplicate rather than a replacement — and a duplicate counts as success,
    because the object is present either way and the key is content-addressed.

    `replace=True` is for keys that are an identity rather than a digest: a
    rendered brief lives at `entities/<slug>.md` forever and is meant to be
    rewritten every time the research behind it changes.
    """
    if _disabled():
        return None
    if len(data) > max_bytes:
        logger.warning(
            "not archiving %s: %.1f MB exceeds the %d MB bucket limit",
            key, len(data) / 1024 / 1024, max_bytes // 1024 // 1024,
        )
        return None
    try:
        async with _client() as client:
            response = await client.post(
                f"/object/{bucket}/{key}",
                content=data,
                headers={"Content-Type": content_type or "application/octet-stream",
                         "x-upsert": "true" if replace else "false"},
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


async def list_buckets() -> list[dict[str, Any]]:
    """Every bucket the service key sees, as Storage reports it. Empty on any failure."""
    if _disabled():
        return []
    try:
        async with _client() as client:
            response = await client.get("/bucket")
        response.raise_for_status()
        found = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("listing buckets failed (%s: %s)", type(exc).__name__, exc)
        return []
    return found if isinstance(found, list) else []


LIST_PAGE = 100
LIST_MAX_FILES = 1000


async def list_all(bucket: str, prefix: str = "") -> list[dict[str, Any]]:
    """Every file under a prefix, folders walked, as {key, size, updated_at}. Empty on any failure."""
    if _disabled():
        return []
    files: list[dict[str, Any]] = []
    folders = [prefix.strip("/")]
    try:
        async with _client() as client:
            while folders and len(files) < LIST_MAX_FILES:
                folder = folders.pop()
                offset = 0
                while True:
                    response = await client.post(
                        f"/object/list/{bucket}",
                        json={"prefix": folder, "limit": LIST_PAGE, "offset": offset,
                              "sortBy": {"column": "name", "order": "asc"}},
                    )
                    response.raise_for_status()
                    page = response.json()
                    if not isinstance(page, list):
                        break
                    for entry in page:
                        key = f"{folder}/{entry['name']}" if folder else entry["name"]
                        if entry.get("id") is None:  # a folder: Storage lists it without an id
                            folders.append(key)
                        elif not entry["name"].startswith("."):  # .emptyFolderPlaceholder
                            meta = entry.get("metadata") or {}
                            files.append({"key": key, "size": meta.get("size"),
                                          "updated_at": entry.get("updated_at")})
                    if len(page) < LIST_PAGE:
                        break
                    offset += LIST_PAGE
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("listing %s/%s failed (%s: %s)", bucket, prefix, type(exc).__name__, exc)
        return []
    return sorted(files, key=lambda f: f["key"])[:LIST_MAX_FILES]


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


async def read(bucket: str, key: str) -> bytes | None:
    """An object that is a record: None only when it does not exist, and raises when Storage failed."""
    if _disabled():
        return None
    async with _client() as client:
        response = await client.get(f"/object/{bucket}/{key}")
    # Storage answers a missing object with 400 and a "not_found" body as well as with 404.
    if response.status_code == 404 or (response.status_code == 400 and "not_found" in response.text):
        return None
    response.raise_for_status()
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

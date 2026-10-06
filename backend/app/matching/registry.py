"""criteria_sets: load a draft, activate a version, read the active one. Rows are never deleted."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from app.matching.config import Criteria, CriteriaError, content_hash, parse_criteria
from app.matching.evaluators import ENGINE_API

ACTIVE = "active"
SET_NAME = "funder-matching"


class NoActiveCriteria(LookupError):
    pass


@dataclass(frozen=True)
class LoadedCriteria:
    criteria: Criteria
    version: int
    content_hash: str
    status: str


async def load_draft(conn: Any, raw: dict, *, git_sha: str | None = None) -> int:
    """Validate and store as a draft. Re-loading identical content is a no-op."""
    criteria = parse_criteria(raw)
    digest = content_hash(raw)
    existing = await (await conn.execute(
        "SELECT content_hash FROM criteria_sets WHERE set_name = %s AND version = %s",
        (criteria.set_, criteria.version))).fetchone()
    if existing:
        if existing["content_hash"] != digest:
            raise CriteriaError(f"version {criteria.version} is already loaded with different content; "
                                "bump version in the file")
        return criteria.version
    await conn.execute(
        "INSERT INTO criteria_sets (set_name, version, content, content_hash, git_sha, engine_api) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (criteria.set_, criteria.version, Jsonb(raw), digest, git_sha, ENGINE_API))
    return criteria.version


async def activate(conn: Any, set_name: str, version: int, *, by: str | None = None) -> None:
    async with conn.transaction():
        row = await (await conn.execute(
            "SELECT status FROM criteria_sets WHERE set_name = %s AND version = %s FOR UPDATE",
            (set_name, version))).fetchone()
        if row is None:
            raise LookupError(f"{set_name} v{version} is not loaded")
        await conn.execute(
            "UPDATE criteria_sets SET status = 'retired', retired_at = now() "
            "WHERE set_name = %s AND status = 'active' AND version <> %s", (set_name, version))
        await conn.execute(
            "UPDATE criteria_sets SET status = 'active', activated_at = now(), retired_at = NULL, "
            "activated_by = %s WHERE set_name = %s AND version = %s", (by, set_name, version))


async def get(conn: Any, set_name: str = SET_NAME, ref: str | int = ACTIVE) -> LoadedCriteria:
    if ref == ACTIVE:
        row = await (await conn.execute(
            "SELECT * FROM criteria_sets WHERE set_name = %s AND status = 'active'", (set_name,))).fetchone()
        if row is None:
            raise NoActiveCriteria(f"no active version of {set_name}: run make criteria-load and criteria-activate")
    else:
        row = await (await conn.execute(
            "SELECT * FROM criteria_sets WHERE set_name = %s AND version = %s", (set_name, int(ref)))).fetchone()
        if row is None:
            raise LookupError(f"{set_name} v{ref} is not loaded")
    return LoadedCriteria(parse_criteria(row["content"]), row["version"], row["content_hash"], row["status"])


async def list_sets(conn: Any, set_name: str = SET_NAME) -> list[dict]:
    return await (await conn.execute(
        "SELECT version, status, content_hash, git_sha, engine_api, loaded_at, activated_at, retired_at "
        "FROM criteria_sets WHERE set_name = %s ORDER BY version", (set_name,))).fetchall()

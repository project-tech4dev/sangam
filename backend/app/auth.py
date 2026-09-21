"""Auth stub for local dev.

Every route already depends on get_current_user so the later swap to Supabase
JWT verification (decode the Bearer token against SUPABASE_JWKS_URL, return the
`sub` claim) changes only this function — no route rework.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Header

DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")  # seeded in db/init/03_dev_user.sql


async def get_current_user(authorization: str | None = Header(default=None)) -> UUID:
    return DEV_USER_ID

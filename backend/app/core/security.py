"""Who is calling: a Supabase access token verified against the project's JWKS, or the dev user.

With SUPABASE_URL unset every request is the seeded dev user. With it set, a request with no
Authorization header is anonymous, a valid Supabase access token is that user, `Bearer dev` is the
dev user when DEV_AUTH is on (local only), and anything else is 401.

AuthMiddleware decides this once per request and leaves it on the request: get_principal and the gates
read it, and PoolDep runs the request's queries as that caller (anon or authenticated).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import jwt
from ag_ui.core.types import RunAgentInput
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings
from app.db.pool import OwnerPoolDep, agent_caller, caveats_given, get_pool
from app.repositories import me as me_repo
from app.repositories import threads
from app.repositories import users as repo

logger = logging.getLogger(__name__)

DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")  # seeded in db/init/03_dev_user.sql


@dataclass(frozen=True)
class CurrentUser:
    id: UUID | None
    is_staff: bool
    auth_user_id: UUID | None = None
    email: str | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.id is None


# The dev user has no Supabase account; 0026 gives its row this auth_user_id so the access functions know it.
DEV_USER = CurrentUser(id=DEV_USER_ID, is_staff=True, auth_user_id=DEV_USER_ID, email="dev@sangam.local")
ANONYMOUS = CurrentUser(id=None, is_staff=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


@lru_cache
def _jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_keys=True)


async def verify_token(token: str, supabase_url: str) -> dict:
    """The token's claims, or InvalidTokenError when it is not a live access token for this project."""
    try:
        signing_key = await asyncio.to_thread(_jwks_client(supabase_url).get_signing_key_from_jwt, token)
    except jwt.PyJWKClientError as exc:
        raise jwt.InvalidTokenError(str(exc)) from exc
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256"],
        audience="authenticated",
        issuer=f"{supabase_url.rstrip('/')}/auth/v1",
        options={"require": ["exp", "sub", "aud", "iss"]},
    )


_authorization_header = APIKeyHeader(
    name="Authorization", auto_error=False, description="`Bearer <Supabase access token>`, or `Bearer dev` locally"
)


async def resolve_principal(authorization: str | None) -> CurrentUser:
    """Who an Authorization header is. Runs as the owner: it writes users rows no caller may write."""
    settings = get_settings()
    if not settings.auth_enabled:
        if settings.dev_auth and authorization and authorization.startswith("Bearer dev:"):
            return await _local_test_user(authorization.removeprefix("Bearer dev:"))
        return DEV_USER

    if not authorization:
        return ANONYMOUS
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("Malformed Authorization header")
    if settings.dev_auth and token == "dev":
        return DEV_USER

    try:
        claims = await verify_token(token, settings.supabase_url)
    except jwt.InvalidTokenError as exc:
        raise _unauthorized(f"Invalid token: {exc}") from exc

    try:
        auth_user_id = UUID(claims["sub"])
    except ValueError as exc:
        raise _unauthorized("Invalid token: sub is not a user id") from exc
    email = claims.get("email")
    if not email:
        raise _unauthorized("Token carries no email")
    meta = claims.get("user_metadata") or {}
    try:
        row = await repo.resolve_auth_user(
            get_pool(),
            auth_user_id=auth_user_id,
            email=email,
            display_name=meta.get("full_name") or meta.get("name"),
        )
    except repo.EmailTakenError as exc:
        logger.warning(
            "sign-in refused: %s is linked to auth user %s, but the token is for auth user %s",
            exc.email,
            exc.linked_auth_user_id,
            auth_user_id,
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This email is already linked to another account"
        ) from exc
    return CurrentUser(id=row["id"], is_staff=row["is_staff"], auth_user_id=auth_user_id, email=email)


async def _local_test_user(email: str) -> CurrentUser:
    """Local testing only: a seeded @local.test user, so each role can be tried without Supabase."""
    if not email.endswith("@local.test"):
        raise _unauthorized("Only @local.test users sign in this way")
    async with get_pool().connection() as conn:
        row = await (await conn.execute(
            "SELECT id, is_staff, auth_user_id FROM users WHERE email = %s AND auth_user_id IS NOT NULL", (email,)
        )).fetchone()
    if row is None:
        raise _unauthorized(f"No local test user {email}")
    return CurrentUser(id=row["id"], is_staff=row["is_staff"], auth_user_id=row["auth_user_id"], email=email)


def _db_identity(principal: CurrentUser) -> tuple[str, str]:
    """The Postgres role and the request.jwt.claims a caller's queries run with."""
    if principal.is_anonymous:
        return "anon", ""
    claims = {"sub": str(principal.auth_user_id), "role": "authenticated", "email": principal.email}
    return "authenticated", json.dumps(claims)


# Nothing here reads data, and /docs must load before anyone can press Authorize.
_OPEN_PATHS = frozenset({"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


class AuthMiddleware:
    """Resolves the caller once per request and leaves it in the request state.

    Plain ASGI rather than BaseHTTPMiddleware, which buffers responses and would break the chat's
    streaming. It answers a bad token itself, since FastAPI's exception handlers never see what is
    raised here. Add it before CORSMiddleware, so CORS wraps it and answers preflights first.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        try:
            principal = await resolve_principal(Headers(scope=scope).get("authorization"))
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
            await response(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        state["principal"] = principal
        state["db_role"], state["db_claims"] = _db_identity(principal)
        await self.app(scope, receive, send)


async def get_principal(
    request: Request, authorization: Annotated[str | None, Security(_authorization_header)] = None
) -> CurrentUser:
    """The caller AuthMiddleware resolved; anonymous without it. The header is declared for /docs' Authorize."""
    return getattr(request.state, "principal", ANONYMOUS)


async def get_current_user(principal: Annotated[CurrentUser, Depends(get_principal)]) -> UUID | None:
    """The caller's users.id, or None when anonymous."""
    return principal.id


async def require_user(user_id: Annotated[UUID | None, Depends(get_current_user)]) -> UUID:
    """The caller's users.id; anonymous is 401. For routes that save or edit."""
    if user_id is None:
        raise _unauthorized("Sign in required")
    return user_id


async def require_principal(principal: Annotated[CurrentUser, Depends(get_principal)]) -> CurrentUser:
    if principal.is_anonymous:
        raise _unauthorized("Sign in required")
    return principal


async def require_staff(principal: Annotated[CurrentUser, Depends(require_principal)]) -> CurrentUser:
    if not principal.is_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff only")
    return principal


# The chat user for this request, read by the tracing hook, which sees the run but not the request.
chat_user_id: ContextVar[UUID | None] = ContextVar("chat_user_id", default=None)


@dataclass(frozen=True)
class CallerScope:
    """What the person behind an agent run may reach. Agent tools use the owner pool, so they ask this."""

    user_id: UUID | None
    is_staff: bool
    # org_id -> admin | member | steward (org_members).
    org_roles: Mapping[int, str] = field(default_factory=dict)
    org_names: Mapping[int, str] = field(default_factory=dict)
    email: str | None = None

    @property
    def steward_of(self) -> list[int]:
        return [org for org, role in self.org_roles.items() if role == "steward"]

    def can_read_org(self, org_id: int | None) -> bool:
        """An org's private data: staff, or any role in that org (a steward reads each org it supports)."""
        return self.is_staff or (org_id is not None and org_id in self.org_roles)

    def can_research_org(self, org_id: int | None) -> bool:
        """Research and save an NGO: staff, or a steward of it. Members and admins research funders."""
        return self.is_staff or (org_id is not None and self.org_roles.get(org_id) == "steward")

    def can_save_funder(self) -> bool:
        return self.is_staff or self.user_id is not None

    def can_edit_proposal(self, org_id: int) -> bool:
        """Write an org's proposals: staff, its admins and its stewards, as 0048's RLS allows."""
        return self.is_staff or self.org_roles.get(org_id) in ("admin", "steward")


# Set with chat_user_id on every chat request. Unset outside one, which tools treat as no access.
chat_scope: ContextVar[CallerScope | None] = ContextVar("chat_scope", default=None)
# The proposal a /proposal run works on, from its thread; the model never names one.
chat_proposal: ContextVar[int | None] = ContextVar("chat_proposal", default=None)


async def caller_scope(pool, principal: CurrentUser) -> CallerScope:
    if principal.id is None or principal.is_staff:
        # Staff pass every check, so their memberships are not needed.
        return CallerScope(user_id=principal.id, is_staff=principal.is_staff, email=principal.email)
    rows = await me_repo.list_memberships(pool, principal.id)
    return CallerScope(principal.id, principal.is_staff, {r["org_id"]: r["role"] for r in rows},
                       {r["org_id"]: r["org_name"] for r in rows}, email=principal.email)


def _thread_title(run: RunAgentInput) -> str | None:
    """The chat's first question, as one line, for the Recent Chats rail."""
    for message in run.messages:
        if message.role != "user":
            continue
        content = message.content
        if not isinstance(content, str):
            content = " ".join(getattr(part, "text", "") or "" for part in content)
        text = " ".join(content.split())
        return text[:120] or None
    return None


async def _own_thread(request: Request, pool: OwnerPoolDep, principal: CurrentUser) -> None:
    try:
        run = RunAgentInput.model_validate(await request.json())
    except (ValueError, ValidationError):
        return  # the endpoint's own body validation answers 422
    owner = await threads.claim_thread(
        pool, thread_id=run.thread_id, user_id=principal.id, title=_thread_title(run)
    )
    # Staff too: a turn checkpoints rows read as this caller, which the owner's next turn would replay.
    if owner != principal.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    chat_user_id.set(principal.id)
    chat_scope.set(await caller_scope(pool, principal))


async def request_scope(
    pool: OwnerPoolDep, principal: Annotated[CurrentUser, Depends(require_principal)]
) -> CallerScope:
    """The signed-in caller's scope, for a route that reads data Import keeps off RLS."""
    return await caller_scope(pool, principal)


async def require_scout(scope: Annotated[CallerScope, Depends(request_scope)]) -> CallerScope:
    """Scout (Import) is for Sangam staff and the stewards of an org; anyone else is 403."""
    if not (scope.is_staff or scope.steward_of):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Scout is for stewards and Sangam staff")
    return scope


async def chat_access(
    request: Request, pool: OwnerPoolDep, principal: Annotated[CurrentUser, Depends(require_principal)]
) -> None:
    """Signed in, and the thread is new or yours; someone else's thread is 404, staff included."""
    await _own_thread(request, pool, principal)


async def ask_access(
    request: Request, pool: OwnerPoolDep, principal: Annotated[CurrentUser, Depends(require_principal)]
) -> None:
    """chat_access, and Ask Sangam's SQL runs as this caller. Import keeps the owner: it writes the catalog."""
    await _own_thread(request, pool, principal)
    agent_caller.set(_db_identity(principal))
    caveats_given.set(set())


async def proposal_chat_access(
    request: Request, pool: OwnerPoolDep, principal: Annotated[CurrentUser, Depends(require_principal)]
) -> None:
    """Your own chat about a proposal you may change: someone else's thread or org is 404, a member is 403."""
    from app.repositories import proposals

    try:
        run = RunAgentInput.model_validate(await request.json())
    except (ValueError, ValidationError):
        return
    parsed = proposals.parse_chat_thread(run.thread_id)
    if parsed is None or parsed[1] != str(principal.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    proposal_id = parsed[0]
    org_id = await proposals.org_of(pool, proposal_id)
    scope = await caller_scope(pool, principal)
    if org_id is None or not scope.can_read_org(org_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    if not scope.can_edit_proposal(org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "You can read this proposal. Ask your organisation's admin to make changes.")
    owner = await threads.claim_thread(pool, thread_id=run.thread_id, user_id=principal.id,
                                       title=_thread_title(run), use_case="proposal", org_id=org_id)
    if owner != principal.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    chat_user_id.set(principal.id)
    chat_scope.set(scope)
    chat_proposal.set(proposal_id)

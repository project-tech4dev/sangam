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
from contextvars import ContextVar
from dataclasses import dataclass
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
from app.db.pool import OwnerPoolDep, get_pool
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


async def _own_thread(request: Request, pool: OwnerPoolDep, principal: CurrentUser) -> None:
    try:
        thread_id = RunAgentInput.model_validate(await request.json()).thread_id
    except (ValueError, ValidationError):
        return  # the endpoint's own body validation answers 422
    owner = await threads.claim_thread(pool, thread_id=thread_id, user_id=principal.id)
    if owner != principal.id and not principal.is_staff:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    chat_user_id.set(principal.id)


async def chat_access(
    request: Request, pool: OwnerPoolDep, principal: Annotated[CurrentUser, Depends(require_principal)]
) -> None:
    """Signed in, and the thread is new or yours (staff may open any); someone else's thread is 404."""
    await _own_thread(request, pool, principal)


async def staff_chat_access(
    request: Request, pool: OwnerPoolDep, principal: Annotated[CurrentUser, Depends(require_staff)]
) -> None:
    await _own_thread(request, pool, principal)

import time
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI, Request

from app.core import security
from app.core.config import Settings
from app.core.security import DEV_USER_ID, AuthMiddleware, CurrentUser, get_principal
from tests.conftest import _SentinelPool

PROJECT = "https://testproject.supabase.co"
ISSUER = f"{PROJECT}/auth/v1"
SUB = UUID("6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f")
USER_ID = UUID("11111111-2222-3333-4444-555555555555")

SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def token(**overrides) -> str:
    claims = {
        "sub": str(SUB),
        "email": "person@ngo.org",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        "user_metadata": {"full_name": "A Person"},
    }
    claims.update(overrides)
    return jwt.encode(claims, SIGNING_KEY, algorithm="ES256", headers={"kid": "test-key"})


@pytest.fixture
def auth(monkeypatch):
    """Auth on for PROJECT; JWKS returns SIGNING_KEY's public half; the users lookup is recorded."""
    calls = []

    def use(**settings):
        monkeypatch.setattr(security, "get_settings", lambda: Settings(_env_file=None, **settings))

    use(supabase_url=PROJECT)
    jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=SIGNING_KEY.public_key()))
    monkeypatch.setattr(security, "_jwks_client", lambda _url: jwks)

    async def fake_resolve(pool, **kwargs):
        calls.append(kwargs)
        return {"id": USER_ID, "is_staff": False}

    monkeypatch.setattr(security.repo, "resolve_auth_user", fake_resolve)
    monkeypatch.setattr(security, "get_pool", _SentinelPool)
    return SimpleNamespace(use=use, calls=calls)


async def call(authorization: str | None = None, path: str = "/whoami") -> httpx.Response:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/whoami")
    async def whoami(request: Request, user: Annotated[CurrentUser, Depends(get_principal)]):
        return {"id": user.id and str(user.id), "email": user.email, "role": request.state.db_role}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    headers = {"Authorization": authorization} if authorization else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        return await c.get(path, headers=headers)


async def test_valid_token_resolves_the_users_row(auth):
    response = await call(f"Bearer {token()}")
    assert response.status_code == 200
    assert response.json() == {"id": str(USER_ID), "email": "person@ngo.org", "role": "authenticated"}
    assert auth.calls == [{"auth_user_id": SUB, "email": "person@ngo.org", "display_name": "A Person"}]


async def test_expired_token_is_401(auth):
    response = await call(f"Bearer {token(exp=int(time.time()) - 60)}")
    assert response.status_code == 401
    assert auth.calls == []


async def test_no_header_is_anonymous(auth):
    response = await call(None)
    assert response.status_code == 200
    assert response.json() == {"id": None, "email": None, "role": "anon"}


async def test_auth_off_means_the_dev_user(auth):
    auth.use(supabase_url="")
    response = await call(f"Bearer {token()}")
    assert response.json()["id"] == str(DEV_USER_ID)
    assert auth.calls == []


async def test_a_bad_token_is_answered_by_the_middleware(auth):
    response = await call("Bearer not-a-token")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_open_paths_skip_the_token(auth):
    response = await call("Bearer not-a-token", path="/health")
    assert response.status_code == 200


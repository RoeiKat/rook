from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.auth import router
from app.auth import ADMIN_COOKIE, VISITOR_COOKIE, Identity, get_identity, hash_password, require_admin, verify_password
from app.config import DEVELOPMENT_SESSION_SECRET, get_settings
from app.database.connection import get_session
from app.database.migrations import migrate_schema
from app.database.models import AdminSession, VisitorSession

CSRF = {"Origin": "http://localhost:5173", "X-CSRF-Protection": "1"}
LOGIN = {"username": "roei", "password": "a test password only"}


@pytest.fixture
async def auth_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-with-at-least-32-characters")
    monkeypatch.setenv("ADMIN_USERNAME", LOGIN["username"])
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password(LOGIN["password"]))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(migrate_schema)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def db_session():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = db_session

    @app.get("/api/identity")
    async def identity(identity: Identity = Depends(get_identity)):
        return {"id": str(identity.visitor_session_id)}

    @app.get("/api/admin-only")
    async def admin_only(identity: Identity = Depends(require_admin)):
        return {"is_admin": identity.is_admin}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield SimpleNamespace(client=client, sessions=sessions)

    await engine.dispose()
    get_settings.cache_clear()


def test_auth_has_only_session_login_and_logout_routes():
    assert {route.path for route in router.routes} == {
        "/api/auth/session", "/api/auth/login", "/api/auth/logout"
    }


def test_development_has_clear_local_defaults(monkeypatch):
    for name in ("APP_ENV", "SESSION_SECRET", "COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.environment == "development"
    assert settings.session_secret == DEVELOPMENT_SESSION_SECRET
    assert settings.cookie_secure is False
    get_settings.cache_clear()


def test_production_requires_an_explicit_session_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        get_settings()
    get_settings.cache_clear()


async def test_visitor_cookie_preserves_identity_and_rejects_tampering(auth_app):
    client = auth_app.client
    await client.get("/api/auth/session")
    first = await client.get("/api/identity")
    assert first.status_code == 200
    first_id = first.json()["id"]
    cookie = client.cookies.get(VISITOR_COOKIE)
    assert cookie
    assert (await client.get("/api/identity")).json()["id"] == first_id

    client.cookies.set(
        VISITOR_COOKIE,
        cookie[:-1] + ("0" if cookie[-1] != "0" else "1"),
        domain="testserver.local",
        path="/api",
    )
    assert (await client.get("/api/identity")).json()["id"] != first_id


async def test_expired_visitor_gets_a_new_identity(auth_app):
    client = auth_app.client
    await client.get("/api/auth/session")
    first_id = (await client.get("/api/identity")).json()["id"]
    async with auth_app.sessions() as session:
        await session.execute(update(VisitorSession).values(
            expires_at=datetime.now(UTC) - timedelta(seconds=1)
        ))
        await session.commit()
    assert (await client.get("/api/identity")).json()["id"] != first_id


async def test_login_session_and_logout(auth_app):
    client = auth_app.client
    assert (await client.get("/api/admin-only")).status_code == 401

    response = await client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    assert response.status_code == 200
    assert response.json() == {"is_admin": True}
    token = client.cookies.get(ADMIN_COOKIE)
    assert token
    assert (await client.get("/api/auth/session")).json() == {"is_admin": True}
    assert (await client.get("/api/admin-only")).status_code == 200

    async with auth_app.sessions() as session:
        stored = await session.scalar(select(AdminSession))
        assert stored.token_hash != token

    response = await client.post("/api/auth/logout", headers=CSRF)
    assert response.json() == {"is_admin": False}
    assert client.cookies.get(ADMIN_COOKIE) is None
    assert (await client.get("/api/admin-only")).status_code == 401


async def test_invalid_or_expired_admin_session_is_rejected(auth_app):
    client = auth_app.client
    bad_login = await client.post(
        "/api/auth/login",
        json={"username": LOGIN["username"], "password": "wrong"},
        headers=CSRF,
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "Invalid username or password"

    await client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    async with auth_app.sessions() as session:
        await session.execute(update(AdminSession).values(
            expires_at=datetime.now(UTC) - timedelta(seconds=1)
        ))
        await session.commit()
    assert (await client.get("/api/auth/session")).json() == {"is_admin": False}


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://localhost:5173"}, {"X-CSRF-Protection": "1"}])
async def test_mutations_require_origin_and_csrf_header(auth_app, headers):
    response = await auth_app.client.post("/api/auth/login", json=LOGIN, headers=headers)
    assert response.status_code == 403


def test_password_hash_round_trip():
    encoded = hash_password("example")
    assert verify_password("example", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("example", "invalid")

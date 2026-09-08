from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.auth import router
from app.auth import (
    ACCESS_COOKIE,
    ADMIN_COOKIE,
    VISITOR_COOKIE,
    Identity,
    get_identity,
    require_admin,
)
from app.auth import hash_password, verify_password
from app.config import get_settings
from app.database.connection import get_session
from app.database.migrations import migrate_schema
from app.database.models import AdminSession, LoginRateLimit, VisitorSession

CSRF = {"Origin": "http://localhost:5173", "X-CSRF-Protection": "1"}
LOGIN = {"username": "roei", "password": "a test password only"}
ACCESS = {"password": "test-admin-page-password"}


def test_auth_routes_have_access_gate_and_no_registration():
    assert {(route.path, tuple(sorted(route.methods))) for route in router.routes} == {
        ("/api/auth/session", ("GET",)),
        ("/api/auth/login", ("POST",)),
        ("/api/auth/logout", ("POST",)),
        ("/api/auth/access", ("GET",)),
        ("/api/auth/access", ("POST",)),
    }


@pytest.fixture
async def auth_app(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-with-at-least-32-characters")
    monkeypatch.setenv("ADMIN_USERNAME", LOGIN["username"])
    monkeypatch.setenv("ADMIN_ACCESS_PASSWORD", ACCESS["password"])
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

    @app.get("/api/restricted")
    async def restricted(identity: Identity = Depends(require_admin)):
        return {"is_admin": identity.is_admin}

    @app.get("/api/identity")
    async def identity_route(identity: Identity = Depends(get_identity)):
        return {"id": str(identity.visitor_session_id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.post("/api/auth/access", json=ACCESS, headers=CSRF)).status_code == 200
        yield SimpleNamespace(app=app, client=client, sessions=sessions)
    await engine.dispose()
    get_settings.cache_clear()


async def test_login_logout_invalidates_server_side_token(auth_app):
    client = auth_app.client
    assert (await client.get("/api/restricted")).status_code == 401
    response = await client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    assert response.status_code == 200
    assert response.json() == {"is_admin": True}
    assert response.headers["cache-control"] == "no-store"
    cookie = client.cookies.get(ADMIN_COOKIE)
    assert cookie
    assert "HttpOnly" in "; ".join(response.headers.get_list("set-cookie"))
    assert (await client.get("/api/auth/session")).json() == {"is_admin": True}
    assert (await client.get("/api/restricted")).status_code == 200
    async with auth_app.sessions() as session:
        stored = await session.scalar(select(AdminSession))
        assert stored.token_hash != cookie
        assert LOGIN["password"] not in repr(stored.__dict__)
    response = await client.post("/api/auth/logout", headers=CSRF)
    assert response.json() == {"is_admin": False}
    assert client.cookies.get(ADMIN_COOKIE) is None
    assert (await client.get("/api/auth/session")).json() == {"is_admin": False}
    client.cookies.set(ADMIN_COOKIE, cookie, domain="testserver.local", path="/api")
    assert (await client.get("/api/restricted")).status_code == 401


async def test_successful_login_rotates_an_existing_admin_session(auth_app):
    client = auth_app.client
    await client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    original = client.cookies.get(ADMIN_COOKIE)
    await client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    assert client.cookies.get(ADMIN_COOKIE) != original
    async with auth_app.sessions() as session:
        assert len(list(await session.scalars(select(AdminSession)))) == 2  # Page access + login.
    client.cookies.set(ADMIN_COOKIE, original, domain="testserver.local", path="/api")
    assert (await client.get("/api/restricted")).status_code == 401


async def test_expired_and_invalid_admin_sessions_are_rejected(auth_app):
    client = auth_app.client
    await client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    async with auth_app.sessions() as session:
        await session.execute(
            update(AdminSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert (await client.get("/api/restricted")).status_code == 401
    assert (await client.get("/api/auth/session")).json() == {"is_admin": False}
    client.cookies.set(ADMIN_COOKIE, "forged-token", domain="testserver.local", path="/api")
    assert (await client.get("/api/restricted")).status_code == 401


async def test_credential_rotation_revokes_existing_sessions(auth_app, monkeypatch):
    client = auth_app.client
    await client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("replacement test password"))
    get_settings.cache_clear()
    assert (await client.get("/api/restricted")).status_code == 401


async def test_login_errors_are_generic_and_attempts_are_database_limited(auth_app):
    client = auth_app.client
    responses = []
    for index in range(5):
        responses.append(
            await client.post(
                "/api/auth/login",
                json={"username": "roei" if index % 2 else "unknown", "password": "incorrect"},
                headers=CSRF,
            )
        )
    assert all(response.status_code == 401 for response in responses)
    assert len({response.text for response in responses}) == 1
    response = await client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    assert response.status_code == 429
    assert "retry-after" in response.headers
    async with auth_app.sessions() as session:
        limiter = await session.scalar(select(LoginRateLimit))
        assert limiter.attempts == 5
        limiter.window_started_at = datetime.now(UTC) - timedelta(minutes=16)
        await session.commit()
    assert (await client.post("/api/auth/login", json=LOGIN, headers=CSRF)).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [{}, {"Origin": "http://localhost:5173"}, {"X-CSRF-Protection": "1"},
     {"Origin": "https://untrusted.example", "X-CSRF-Protection": "1"}],
)
async def test_auth_mutations_require_trusted_origin_and_custom_header(auth_app, headers):
    client = auth_app.client
    assert (await client.post("/api/auth/login", json=LOGIN, headers=headers)).status_code == 403
    assert (await client.post("/api/auth/logout", headers=headers)).status_code == 403


async def test_visitor_cookie_survives_refresh_and_cannot_be_forged(auth_app):
    client = auth_app.client
    response = await client.get("/api/auth/session")
    assert response.json() == {"is_admin": False}
    visitor_cookie = client.cookies.get(VISITOR_COOKIE)
    assert visitor_cookie
    original_id = (await client.get("/api/identity")).json()["id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=auth_app.app),
        base_url="http://testserver",
        cookies=client.cookies,
    ) as refreshed:
        assert (await refreshed.get("/api/identity")).json()["id"] == original_id
    client.cookies.set(
        VISITOR_COOKIE, visitor_cookie[:-1] + ("0" if visitor_cookie[-1] != "0" else "1"),
        domain="testserver.local", path="/api",
    )
    assert (await client.get("/api/identity")).json()["id"] != original_id


async def test_expired_visitor_cookie_receives_new_ownership(auth_app):
    client = auth_app.client
    await client.get("/api/auth/session")
    initial_cookie = client.cookies.get(VISITOR_COOKIE)
    async with auth_app.sessions() as session:
        await session.execute(
            update(VisitorSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    await client.get("/api/auth/session")
    assert client.cookies.get(VISITOR_COOKIE) != initial_cookie


@pytest.mark.parametrize("missing_setting", ["SESSION_SECRET", "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "ADMIN_ACCESS_PASSWORD"])
async def test_missing_configuration_never_grants_admin_access(auth_app, monkeypatch, missing_setting):
    monkeypatch.setenv(missing_setting, "")
    get_settings.cache_clear()
    client = auth_app.client
    assert (await client.get("/api/restricted")).status_code == 401
    assert (await client.get("/api/auth/session")).json() == {"is_admin": False}
    expected = 403 if missing_setting in {"SESSION_SECRET", "ADMIN_ACCESS_PASSWORD"} else 401
    assert (await client.post("/api/auth/login", json=LOGIN, headers=CSRF)).status_code == expected
    if missing_setting == "SESSION_SECRET":
        assert (await client.get("/api/identity")).status_code == 503


async def test_cookie_defaults_are_secure_and_http_only(auth_app, monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE")
    get_settings.cache_clear()
    response = await auth_app.client.post("/api/auth/login", json=LOGIN, headers=CSRF)
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert all("Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie for cookie in cookies)


async def test_login_cannot_bypass_access_password(auth_app, monkeypatch):
    from unittest.mock import Mock
    verify = Mock()
    monkeypatch.setattr("app.api.auth.verify_password", verify)
    client = auth_app.client
    client.cookies.clear()
    assert (await client.get("/api/auth/access")).status_code == 403
    assert (await client.post("/api/auth/login", json=LOGIN, headers=CSRF)).status_code == 403
    verify.assert_not_called()
    assert (await client.post("/api/auth/access", json={"password": "wrong"}, headers=CSRF)).status_code == 403
    assert client.cookies.get(ACCESS_COOKIE) is None
    response = await client.post("/api/auth/access", json=ACCESS, headers=CSRF)
    assert response.json() == {"allowed": True}
    assert ACCESS["password"] not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert (await client.get("/api/auth/access")).status_code == 200
    assert (await client.get("/api/restricted")).status_code == 401


async def test_access_cookie_cannot_be_used_as_an_administrator_session(auth_app):
    client = auth_app.client
    access_token = client.cookies.get(ACCESS_COOKIE)
    client.cookies.set(ADMIN_COOKIE, access_token, domain="testserver.local", path="/api")
    assert (await client.get("/api/auth/access")).status_code == 200
    assert (await client.get("/api/restricted")).status_code == 401


async def test_logout_revokes_access_cookie_even_when_replayed(auth_app):
    client = auth_app.client
    token = client.cookies.get(ACCESS_COOKIE)
    assert (await client.post("/api/auth/logout", headers=CSRF)).status_code == 200
    assert client.cookies.get(ACCESS_COOKIE) is None
    client.cookies.set(ACCESS_COOKIE, token, domain="testserver.local", path="/api")
    assert (await client.get("/api/auth/access")).status_code == 403
    assert (await client.post("/api/auth/login", json=LOGIN, headers=CSRF)).status_code == 403


async def test_access_expiry_tampering_and_password_rotation(auth_app, monkeypatch):
    client = auth_app.client
    async with auth_app.sessions() as session:
        await session.execute(update(AdminSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await session.commit()
    assert (await client.get("/api/auth/access")).status_code == 403
    await client.post("/api/auth/access", json=ACCESS, headers=CSRF)
    token = client.cookies.get(ACCESS_COOKIE)
    client.cookies.set(ACCESS_COOKIE, "tampered-token", domain="testserver.local", path="/api")
    assert (await client.get("/api/auth/access")).status_code == 403
    client.cookies.set(ACCESS_COOKIE, token, domain="testserver.local", path="/api")
    monkeypatch.setenv("ADMIN_ACCESS_PASSWORD", "replacement-access-password")
    get_settings.cache_clear()
    assert (await client.get("/api/auth/access")).status_code == 403
    assert (await client.post("/api/auth/access", json=ACCESS, headers=CSRF)).status_code == 403


async def test_access_password_attempts_are_limited_separately_from_login(auth_app):
    client = auth_app.client
    for _ in range(5):
        assert (await client.post("/api/auth/access", json={"password": "wrong"}, headers=CSRF)).status_code == 403
    assert (await client.post("/api/auth/access", json=ACCESS, headers=CSRF)).status_code == 429
    # Existing page access still permits a valid login; the lockouts are separate.
    assert (await client.post("/api/auth/login", json=LOGIN, headers=CSRF)).status_code == 200


async def test_access_route_requires_csrf(auth_app):
    assert (await auth_app.client.post("/api/auth/access", json=ACCESS)).status_code == 403


def test_password_hashes_use_unique_salts_and_reject_corrupt_inputs():
    first, second = hash_password("example"), hash_password("example")
    assert first != second
    assert verify_password("example", first)
    assert not verify_password("wrong", first)
    assert not verify_password("example", "invalid")
    assert not verify_password("example", "pbkdf2_sha256$600000$invalid$invalid")


@pytest.mark.parametrize("origin", ["*", "https://*.example.com", "https://example.com/path", "null"])
def test_credentialed_origins_must_be_explicit(monkeypatch, origin):
    monkeypatch.setenv("FRONTEND_ORIGINS", origin)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="explicit"):
        get_settings()
    get_settings.cache_clear()

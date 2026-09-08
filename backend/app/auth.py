"""Browser sessions, administrator password verification, and login throttling.

Generate the single administrator's password hash with: python -m app.auth
There is no user registration or user-management system.
"""
import base64
import getpass
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database.connection import get_session
from app.database.models import AdminSession, LoginRateLimit, VisitorSession

ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "$".join(
        (
            "pbkdf2_sha256",
            str(ITERATIONS),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_text, digest_text = encoded.split("$")
        iterations = int(rounds)
        if algorithm != "pbkdf2_sha256" or not ITERATIONS <= iterations <= 2_000_000:
            return False
        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(digest_text, validate=True)
        if len(salt) < 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def main() -> None:
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not password or password != confirmation:
        raise SystemExit("Passwords must be nonempty and match")
    print(hash_password(password))



async def reserve_login_attempt(
    session: AsyncSession, request: Request, settings: Settings, *, scope: str = "login"
) -> str:
    """Reserve attempts before password work, serialized per IP across API workers."""
    address = request.client.host if request.client else "unknown"
    key = hmac.new(
        settings.session_secret.encode(), (scope + ":" + address).encode(), hashlib.sha256
    ).hexdigest()
    now = datetime.now(UTC)
    dialect = session.get_bind().dialect.name
    insert = postgres_insert if dialect == "postgresql" else sqlite_insert
    await session.execute(
        insert(LoginRateLimit)
        .values(key=key, attempts=0, window_started_at=now)
        .on_conflict_do_nothing(index_elements=[LoginRateLimit.key])
    )
    limiter = await session.scalar(
        select(LoginRateLimit).where(LoginRateLimit.key == key).with_for_update()
    )
    assert limiter is not None
    started = limiter.window_started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if now - started >= timedelta(seconds=settings.login_window_seconds):
        limiter.attempts = 0
        limiter.window_started_at = now
    if limiter.attempts >= settings.login_max_attempts:
        await session.rollback()
        raise HTTPException(
            status_code=429,
            detail="Unable to sign in. Try again later.",
            headers={"Retry-After": str(settings.login_window_seconds)},
        )
    limiter.attempts += 1
    await session.commit()
    return key


async def clear_login_attempts(session: AsyncSession, key: str) -> None:
    await session.execute(delete(LoginRateLimit).where(LoginRateLimit.key == key))

VISITOR_COOKIE = "rook_visitor"
ADMIN_COOKIE = "rook_admin"
ACCESS_COOKIE = "rook_admin_access"
COOKIE_PATH = "/api"


@dataclass(frozen=True)
class Identity:
    visitor_session_id: uuid.UUID
    is_admin: bool = False
    visitor_cookie: str | None = None


def configured_secret(settings: Settings) -> bool:
    return len(settings.session_secret) >= 32


def credential_fingerprint(settings: Settings) -> str:
    return hmac.new(
        settings.session_secret.encode(),
        (settings.admin_username + "\0" + settings.admin_password_hash).encode(),
        hashlib.sha256,
    ).hexdigest()


def hash_admin_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def access_fingerprint(settings: Settings) -> str:
    return hmac.new(
        settings.session_secret.encode(),
        ("admin-access\0" + settings.admin_access_password).encode(), hashlib.sha256,
    ).hexdigest()


async def valid_access_session(request: Request, session: AsyncSession, settings: Settings) -> bool:
    token = request.cookies.get(ACCESS_COOKIE, "")
    if not (configured_secret(settings) and settings.admin_access_password and token) or len(token) > 128:
        return False
    return await session.scalar(select(AdminSession.token_hash).where(
        AdminSession.token_hash == hash_admin_token(token),
        AdminSession.credential_fingerprint == access_fingerprint(settings),
        AdminSession.expires_at > datetime.now(UTC),
    )) is not None


async def require_admin_access(request: Request, session: AsyncSession = Depends(get_session)) -> None:
    if not await valid_access_session(request, session, get_settings()):
        raise HTTPException(status_code=403, detail="Administrator page access required")


def sign_visitor_id(session_id: uuid.UUID, settings: Settings) -> str:
    value = session_id.hex
    signature = hmac.new(
        settings.session_secret.encode(), ("visitor:" + value).encode(), hashlib.sha256
    ).hexdigest()
    return value + "." + signature


def parse_visitor_id(cookie: str, settings: Settings) -> uuid.UUID | None:
    if len(cookie) != 97:
        return None
    try:
        session_id = uuid.UUID(hex=cookie.split(".", 1)[0])
    except ValueError:
        return None
    if not hmac.compare_digest(cookie.encode(), sign_visitor_id(session_id, settings).encode()):
        return None
    return session_id


async def valid_admin_session(
    request: Request, session: AsyncSession, settings: Settings
) -> AdminSession | None:
    if not (configured_secret(settings) and settings.admin_username and settings.admin_password_hash):
        return None
    if not await valid_access_session(request, session, settings):
        return None
    token = request.cookies.get(ADMIN_COOKIE, "")
    if not token or len(token) > 128:
        return None
    return await session.scalar(
        select(AdminSession).where(
            AdminSession.token_hash == hash_admin_token(token),
            AdminSession.expires_at > datetime.now(UTC),
            AdminSession.credential_fingerprint == credential_fingerprint(settings),
        )
    )


async def get_identity(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Identity:
    settings = get_settings()
    if not configured_secret(settings):
        raise HTTPException(status_code=503, detail="Browser sessions are unavailable")
    is_admin = await valid_admin_session(request, session, settings) is not None
    visitor_id = parse_visitor_id(request.cookies.get(VISITOR_COOKIE, ""), settings)
    if visitor_id is not None:
        existing = await session.scalar(
            select(VisitorSession.id).where(
                VisitorSession.id == visitor_id,
                VisitorSession.expires_at > datetime.now(UTC),
            )
        )
        if existing is not None:
            return Identity(visitor_session_id=visitor_id, is_admin=is_admin)
    visitor = VisitorSession(
        id=uuid.uuid4(), expires_at=datetime.now(UTC) + timedelta(days=settings.visitor_session_days)
    )
    session.add(visitor)
    await session.commit()
    return Identity(
        visitor_session_id=visitor.id,
        is_admin=is_admin,
        visitor_cookie=sign_visitor_id(visitor.id, settings),
    )


async def require_admin(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Identity:
    if await valid_admin_session(request, session, get_settings()) is None:
        raise HTTPException(status_code=401, detail="Administrator authentication required")
    return await get_identity(request, session)


async def require_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if (
        request.headers.get("origin") not in get_settings().frontend_origins
        or request.headers.get("x-csrf-protection") != "1"
    ):
        raise HTTPException(status_code=403, detail="Request origin verification failed")


def apply_visitor_cookie(response: Response, identity: Identity) -> None:
    if identity.visitor_cookie is None:
        return
    settings = get_settings()
    response.set_cookie(
        VISITOR_COOKIE,
        identity.visitor_cookie,
        max_age=settings.visitor_session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def apply_admin_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=settings.admin_session_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(
        ADMIN_COOKIE,
        path=COOKIE_PATH,
        secure=get_settings().cookie_secure,
        httponly=True,
        samesite="lax",
    )


if __name__ == "__main__":
    main()

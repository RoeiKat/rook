"""Small authentication helpers for visitor ownership and the admin login."""

import base64
import getpass
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database.connection import get_session
from app.database.models import AdminSession, VisitorSession

ITERATIONS = 600_000
VISITOR_SESSION_DAYS = 365
ADMIN_SESSION_SECONDS = 8 * 60 * 60
VISITOR_COOKIE = "rook_visitor"
ADMIN_COOKIE = "rook_admin"
COOKIE_PATH = "/api"


@dataclass(frozen=True)
class Identity:
    visitor_session_id: uuid.UUID
    is_admin: bool = False
    visitor_cookie: str | None = None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "$".join((
        "pbkdf2_sha256",
        str(ITERATIONS),
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    ))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_text, digest_text = encoded.split("$")
        iterations = int(rounds)
        if algorithm != "pbkdf2_sha256" or not ITERATIONS <= iterations <= 2_000_000:
            return False
        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(digest_text, validate=True)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return len(salt) >= 16 and len(expected) == 32 and hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def credential_fingerprint(settings: Settings) -> str:
    credentials = settings.admin_username + "\0" + settings.admin_password_hash
    return hmac.new(settings.session_secret.encode(), credentials.encode(), hashlib.sha256).hexdigest()


def hash_admin_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_visitor_id(session_id: uuid.UUID, settings: Settings) -> str:
    value = session_id.hex
    signature = hmac.new(
        settings.session_secret.encode(), ("visitor:" + value).encode(), hashlib.sha256
    ).hexdigest()
    return value + "." + signature


def parse_visitor_id(cookie: str, settings: Settings) -> uuid.UUID | None:
    try:
        value, _ = cookie.split(".", 1)
        session_id = uuid.UUID(hex=value)
    except (ValueError, AttributeError):
        return None
    expected = sign_visitor_id(session_id, settings)
    return session_id if hmac.compare_digest(cookie, expected) else None


async def is_admin(request: Request, session: AsyncSession, settings: Settings) -> bool:
    token = request.cookies.get(ADMIN_COOKIE, "")
    if not token or not settings.admin_username or not settings.admin_password_hash:
        return False
    stored = await session.scalar(select(AdminSession).where(
        AdminSession.token_hash == hash_admin_token(token),
        AdminSession.credential_fingerprint == credential_fingerprint(settings),
        AdminSession.expires_at > datetime.now(UTC),
    ))
    return stored is not None


async def get_identity(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Identity:
    """Return the browser owner, creating it on the first request."""
    settings = get_settings()
    visitor_id = parse_visitor_id(request.cookies.get(VISITOR_COOKIE, ""), settings)
    if visitor_id:
        existing = await session.scalar(select(VisitorSession.id).where(
            VisitorSession.id == visitor_id,
            VisitorSession.expires_at > datetime.now(UTC),
        ))
        if existing:
            return Identity(visitor_id, await is_admin(request, session, settings))

    visitor = VisitorSession(
        id=uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=VISITOR_SESSION_DAYS),
    )
    session.add(visitor)
    await session.commit()
    return Identity(
        visitor.id,
        await is_admin(request, session, settings),
        sign_visitor_id(visitor.id, settings),
    )


async def require_admin(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Identity:
    identity = await get_identity(request, session)
    if not identity.is_admin:
        raise HTTPException(status_code=401, detail="Administrator authentication required")
    return identity


async def require_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    settings = get_settings()
    if (
        request.headers.get("origin") not in settings.frontend_origins
        or request.headers.get("x-csrf-protection") != "1"
    ):
        raise HTTPException(status_code=403, detail="Request origin verification failed")


def apply_visitor_cookie(response: Response, identity: Identity) -> None:
    if identity.visitor_cookie:
        settings = get_settings()
        response.set_cookie(
            VISITOR_COOKIE,
            identity.visitor_cookie,
            max_age=VISITOR_SESSION_DAYS * 86400,
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
        max_age=ADMIN_SESSION_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_COOKIE, path=COOKIE_PATH)


def main() -> None:
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not password or password != confirmation:
        raise SystemExit("Passwords must be nonempty and match")
    print(hash_password(password))


if __name__ == "__main__":
    main()

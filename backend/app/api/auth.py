"""Administrator login endpoints."""

import hmac
import hashlib
import math
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth import (
    ADMIN_SESSION_SECONDS,
    ADMIN_COOKIE,
    apply_admin_cookie,
    apply_visitor_cookie,
    clear_admin_cookie,
    credential_fingerprint,
    get_identity,
    hash_admin_token,
    require_csrf,
    verify_password,
)
from app.config import get_settings
from app.database.connection import get_session
from app.database.models import AdminLoginFailure, AdminSession

router = APIRouter(prefix="/api/auth", dependencies=[Depends(require_csrf)])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


def login_client_key(request: Request, session_secret: str) -> str:
    address = request.client.host if request.client else "unknown"
    return hmac.new(
        session_secret.encode(), f"admin-login:{address}".encode(), hashlib.sha256
    ).hexdigest()


async def login_limit(
    session: AsyncSession, client_key: str, window_seconds: int
) -> tuple[int, datetime | None]:
    cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
    row = (await session.execute(
        select(func.count(AdminLoginFailure.id), func.min(AdminLoginFailure.attempted_at))
        .where(
            AdminLoginFailure.client_key == client_key,
            AdminLoginFailure.attempted_at >= cutoff,
        )
    )).one()
    return int(row[0]), row[1]


def rate_limit_error(oldest: datetime | None, window_seconds: int) -> HTTPException:
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    retry_after = window_seconds if oldest is None else max(
        1, math.ceil((oldest + timedelta(seconds=window_seconds) - datetime.now(UTC)).total_seconds())
    )
    return HTTPException(
        status_code=429,
        detail="Too many login attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


@router.get("/session")
async def auth_session(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, bool]:
    identity = await get_identity(request, session)
    apply_visitor_cookie(response, identity)
    response.headers["Cache-Control"] = "no-store"
    return {"is_admin": identity.is_admin}


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    settings = get_settings()
    client_key = login_client_key(request, settings.session_secret)
    attempts, oldest_attempt = await login_limit(
        session, client_key, settings.admin_login_window_seconds
    )
    if attempts >= settings.admin_login_max_attempts:
        raise rate_limit_error(oldest_attempt, settings.admin_login_window_seconds)

    password_valid = await run_in_threadpool(
        verify_password, body.password, settings.admin_password_hash
    )
    username_valid = hmac.compare_digest(body.username, settings.admin_username)
    if not settings.admin_username or not (username_valid and password_valid):
        attempted_at = datetime.now(UTC)
        await session.execute(delete(AdminLoginFailure).where(
            AdminLoginFailure.attempted_at < attempted_at - timedelta(
                seconds=settings.admin_login_window_seconds
            )
        ))
        session.add(AdminLoginFailure(client_key=client_key, attempted_at=attempted_at))
        await session.commit()
        if attempts + 1 >= settings.admin_login_max_attempts:
            raise rate_limit_error(
                oldest_attempt or attempted_at, settings.admin_login_window_seconds
            )
        raise HTTPException(status_code=401, detail="Invalid username or password")

    identity = await get_identity(request, session)
    old_token = request.cookies.get(ADMIN_COOKIE)
    await session.execute(delete(AdminLoginFailure).where(
        AdminLoginFailure.client_key == client_key
    ))
    if old_token:
        await session.execute(delete(AdminSession).where(
            AdminSession.token_hash == hash_admin_token(old_token)
        ))

    token = secrets.token_urlsafe(32)
    session.add(AdminSession(
        token_hash=hash_admin_token(token),
        credential_fingerprint=credential_fingerprint(settings),
        expires_at=datetime.now(UTC) + timedelta(seconds=ADMIN_SESSION_SECONDS),
    ))
    await session.commit()
    apply_visitor_cookie(response, identity)
    apply_admin_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return {"is_admin": True}


@router.post("/logout")
async def logout(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, bool]:
    token = request.cookies.get(ADMIN_COOKIE)
    if token:
        await session.execute(delete(AdminSession).where(
            AdminSession.token_hash == hash_admin_token(token)
        ))
        await session.commit()
    clear_admin_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return {"is_admin": False}

import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth import (
    ACCESS_COOKIE,
    ADMIN_COOKIE,
    COOKIE_PATH,
    access_fingerprint,
    apply_admin_cookie,
    apply_visitor_cookie,
    clear_admin_cookie,
    clear_login_attempts,
    configured_secret,
    credential_fingerprint,
    get_identity,
    hash_admin_token,
    require_csrf,
    require_admin_access,
    reserve_login_attempt,
    verify_password,
)
from app.config import get_settings
from app.database.connection import get_session
from app.database.models import AdminSession

router = APIRouter(prefix="/api/auth", dependencies=[Depends(require_csrf)])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class AccessRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@router.get("/access", dependencies=[Depends(require_admin_access)])
async def check_access(response: Response) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    return {"allowed": True}


@router.post("/access")
async def unlock_access(
    body: AccessRequest, request: Request, response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    settings = get_settings()
    if not (configured_secret(settings) and settings.admin_access_password):
        raise HTTPException(status_code=403, detail="Administrator page access required")
    attempt_key = await reserve_login_attempt(session, request, settings, scope="admin-access")
    if not hmac.compare_digest(body.password.encode(), settings.admin_access_password.encode()):
        raise HTTPException(status_code=403, detail="Administrator page access required")
    old_token = request.cookies.get(ACCESS_COOKIE, "")
    if old_token and len(old_token) <= 128:
        await session.execute(delete(AdminSession).where(AdminSession.token_hash == hash_admin_token(old_token)))
    token = secrets.token_urlsafe(32)
    session.add(AdminSession(
        token_hash=hash_admin_token(token), credential_fingerprint=access_fingerprint(settings),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.admin_session_seconds),
    ))
    await clear_login_attempts(session, attempt_key)
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        ACCESS_COOKIE, token, max_age=settings.admin_session_seconds, httponly=True,
        secure=settings.cookie_secure, samesite="lax", path=COOKIE_PATH,
    )
    return {"allowed": True}


@router.get("/session")
async def auth_session(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    if not configured_secret(get_settings()):
        return {"is_admin": False}
    identity = await get_identity(request, session)
    apply_visitor_cookie(response, identity)
    return {"is_admin": identity.is_admin}


@router.post("/login", dependencies=[Depends(require_admin_access)])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    settings = get_settings()
    if not (configured_secret(settings) and settings.admin_username and settings.admin_password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    attempt_key = await reserve_login_attempt(session, request, settings)
    password_valid = await run_in_threadpool(
        verify_password, body.password, settings.admin_password_hash
    )
    username_valid = hmac.compare_digest(body.username.encode(), settings.admin_username.encode())
    if not (password_valid and username_valid):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    identity = await get_identity(request, session)
    old_token = request.cookies.get(ADMIN_COOKIE)
    if old_token:
        await session.execute(
            delete(AdminSession).where(AdminSession.token_hash == hash_admin_token(old_token))
        )
    token = secrets.token_urlsafe(32)
    session.add(
        AdminSession(
            token_hash=hash_admin_token(token),
            credential_fingerprint=credential_fingerprint(settings),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.admin_session_seconds),
        )
    )
    await clear_login_attempts(session, attempt_key)
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    apply_visitor_cookie(response, identity)
    apply_admin_cookie(response, token)
    return {"is_admin": True}


@router.post("/logout")
async def logout(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, bool]:
    for cookie in (ADMIN_COOKIE, ACCESS_COOKIE):
        token = request.cookies.get(cookie)
        if token and len(token) <= 128:
            await session.execute(delete(AdminSession).where(AdminSession.token_hash == hash_admin_token(token)))
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    clear_admin_cookie(response)
    response.delete_cookie(
        ACCESS_COOKIE, path=COOKIE_PATH, secure=get_settings().cookie_secure,
        httponly=True, samesite="lax",
    )
    return {"is_admin": False}

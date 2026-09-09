"""Administrator login endpoints."""

import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete
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
from app.database.models import AdminSession

router = APIRouter(prefix="/api/auth", dependencies=[Depends(require_csrf)])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


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
    password_valid = await run_in_threadpool(
        verify_password, body.password, settings.admin_password_hash
    )
    username_valid = hmac.compare_digest(body.username, settings.admin_username)
    if not settings.admin_username or not (username_valid and password_valid):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    identity = await get_identity(request, session)
    old_token = request.cookies.get(ADMIN_COOKIE)
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

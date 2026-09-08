"""Optional integration coverage against an isolated real PostgreSQL schema."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.auth import reserve_login_attempt
from app.config import Settings
from app.database.migrations import migrate_schema
from app.database.models import LoginRateLimit


@pytest.mark.postgres
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured")
async def test_postgres_login_limit_is_atomic_across_concurrent_connections():
    url = os.environ["TEST_DATABASE_URL"]
    schema = "auth_test_" + uuid.uuid4().hex
    control_engine = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with control_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(migrate_schema)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(
            admin_username="test",
            admin_password_hash="unused-by-rate-limit",
            session_secret="test-secret-that-is-at-least-32-characters",
            frontend_origins=("http://localhost:5173",),
            cookie_secure=False,
        )
        request = Request({"type": "http", "client": ("127.0.0.1", 1234)})

        async def reserve():
            async with sessions() as session:
                try:
                    await reserve_login_attempt(session, request, settings)
                    return 200
                except HTTPException as exc:
                    return exc.status_code

        statuses = await asyncio.gather(*(reserve() for _ in range(12)))
        assert statuses.count(200) == settings.login_max_attempts
        assert statuses.count(429) == 12 - settings.login_max_attempts
        async with sessions() as session:
            limiter = await session.scalar(select(LoginRateLimit))
            assert limiter.attempts == settings.login_max_attempts
        # A different connection and session factory still see the persisted limit.
        async with async_sessionmaker(engine)() as session:
            with pytest.raises(HTTPException) as error:
                await reserve_login_attempt(session, request, settings)
            assert error.value.status_code == 429
        async with sessions() as session:
            await session.execute(
                update(LoginRateLimit).values(
                    window_started_at=datetime.now(UTC) - timedelta(minutes=16)
                )
            )
            await session.commit()
        assert await reserve() == 200
        async with sessions() as session:
            assert (await session.scalar(select(LoginRateLimit))).attempts == 1
    finally:
        await engine.dispose()
        async with control_engine.begin() as connection:
            # Only the unique schema created by this test is removed.
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await control_engine.dispose()

"""Shared deployment and security settings loaded from backend/.env."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEVELOPMENT_SESSION_SECRET = "rook-local-development-session-secret"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://rook:rook@localhost:5432/rook"


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_secret: str
    frontend_origins: tuple[str, ...]
    cookie_secure: bool
    environment: str = "development"
    admin_username: str = ""
    admin_password_hash: str = ""
    document_storage_local_path: str = ""
    document_upload_max_bytes: int = 10 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    environment = os.getenv("APP_ENV", "development").lower()
    if environment not in {"development", "production", "test"}:
        raise ValueError("APP_ENV must be development, production, or test")

    session_secret = os.getenv("SESSION_SECRET", "")
    if len(session_secret) < 32 and environment != "production":
        session_secret = DEVELOPMENT_SESSION_SECRET
    if len(session_secret) < 32:
        raise ValueError("SESSION_SECRET must contain at least 32 characters")

    origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    )
    if not origins:
        raise ValueError("FRONTEND_ORIGINS must contain at least one origin")

    secure_value = os.getenv("COOKIE_SECURE", "").lower()
    if secure_value not in {"", "true", "false"}:
        raise ValueError("COOKIE_SECURE must be true or false")
    cookie_secure = environment == "production" if not secure_value else secure_value == "true"

    try:
        upload_max_bytes = int(os.getenv("DOCUMENT_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024)))
    except ValueError as exc:
        raise ValueError("DOCUMENT_UPLOAD_MAX_BYTES must be an integer") from exc
    if upload_max_bytes <= 0:
        raise ValueError("DOCUMENT_UPLOAD_MAX_BYTES must be greater than zero")

    default_document_path = str(Path(__file__).resolve().parents[1] / "ingestion" / "documents")

    return Settings(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        environment=environment,
        session_secret=session_secret,
        frontend_origins=origins,
        cookie_secure=cookie_secure,
        admin_username=os.getenv("ADMIN_USERNAME", ""),
        admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", ""),
        document_storage_local_path=os.getenv("DOCUMENT_STORAGE_LOCAL_PATH", default_document_path),
        document_upload_max_bytes=upload_max_bytes,
    )

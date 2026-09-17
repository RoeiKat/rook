"""Shared deployment and security settings loaded from backend/.env."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEVELOPMENT_SESSION_SECRET = "rook-local-development-session-secret"
DEFAULT_DATABASE_URL = "postgresql+asyncpg://rook:rook@localhost:5432/rook"
DEFAULT_DOCUMENT_UPLOAD_MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    database_url: str
    database_migration_url: str
    session_secret: str
    frontend_origins: tuple[str, ...]
    cookie_secure: bool
    environment: str = "development"
    admin_username: str = ""
    admin_password_hash: str = ""
    admin_login_max_attempts: int = 5
    admin_login_window_seconds: int = 15 * 60
    document_storage_provider: str = "local"
    document_storage_local_path: str = ""
    s3_bucket: str = ""
    aws_endpoint_url_s3: str = ""
    aws_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    document_upload_max_bytes: int = DEFAULT_DOCUMENT_UPLOAD_MAX_BYTES


def async_database_url(value: str) -> str:
    """Adapt a standard Postgres URL for SQLAlchemy's asyncpg dialect."""
    parts = urlsplit(value)
    if parts.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        return value

    query: list[tuple[str, str]] = []
    ssl_mode: str | None = None
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            ssl_mode = item
        elif key != "channel_binding":
            query.append((key, item))
    if ssl_mode and not any(key == "ssl" for key, _ in query):
        query.append(("ssl", ssl_mode))

    return urlunsplit((
        "postgresql+asyncpg",
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment,
    ))


def boolean_setting(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


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

    cookie_secure = boolean_setting("COOKIE_SECURE", environment == "production")

    try:
        upload_max_bytes = int(os.getenv(
            "DOCUMENT_UPLOAD_MAX_BYTES",
            str(DEFAULT_DOCUMENT_UPLOAD_MAX_BYTES),
        ))
    except ValueError as exc:
        raise ValueError("DOCUMENT_UPLOAD_MAX_BYTES must be an integer") from exc
    if upload_max_bytes <= 0:
        raise ValueError("DOCUMENT_UPLOAD_MAX_BYTES must be greater than zero")

    try:
        admin_login_max_attempts = int(os.getenv("ADMIN_LOGIN_MAX_ATTEMPTS", "5"))
        admin_login_window_seconds = int(os.getenv("ADMIN_LOGIN_WINDOW_SECONDS", "900"))
    except ValueError as exc:
        raise ValueError("Administrator login rate-limit settings must be integers") from exc
    if admin_login_max_attempts <= 0 or admin_login_window_seconds <= 0:
        raise ValueError("Administrator login rate-limit settings must be greater than zero")

    default_document_path = str(Path(__file__).resolve().parents[1] / "ingestion" / "documents")
    raw_database_url = (
        os.getenv("DATABASE_URL_POOLED")
        or os.getenv("DATABASE_URL")
        or DEFAULT_DATABASE_URL
    )
    raw_migration_url = (
        os.getenv("DATABASE_URL_UNPOOLED")
        or os.getenv("DATABASE_URL")
        or raw_database_url
    )

    return Settings(
        database_url=async_database_url(raw_database_url),
        database_migration_url=async_database_url(raw_migration_url),
        environment=environment,
        session_secret=session_secret,
        frontend_origins=origins,
        cookie_secure=cookie_secure,
        admin_username=os.getenv("ADMIN_USERNAME", ""),
        admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", ""),
        admin_login_max_attempts=admin_login_max_attempts,
        admin_login_window_seconds=admin_login_window_seconds,
        document_storage_provider=os.getenv("DOCUMENT_STORAGE_PROVIDER", "local").lower(),
        document_storage_local_path=os.getenv("DOCUMENT_STORAGE_LOCAL_PATH", default_document_path),
        s3_bucket=os.getenv("S3_BUCKET", ""),
        aws_endpoint_url_s3=os.getenv("AWS_ENDPOINT_URL_S3", ""),
        aws_region=os.getenv("AWS_REGION", ""),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        document_upload_max_bytes=upload_max_bytes,
    )

"""Backend-only session settings. No administrator credentials have defaults."""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    admin_username: str
    admin_password_hash: str = field(repr=False)
    session_secret: str = field(repr=False)
    frontend_origins: tuple[str, ...]
    cookie_secure: bool
    admin_access_password: str = field(default="", repr=False)
    visitor_session_days: int = 365
    admin_session_seconds: int = 8 * 60 * 60
    login_window_seconds: int = 15 * 60
    login_max_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv(
            "FRONTEND_ORIGINS", os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
        ).split(",")
        if origin.strip()
    )
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or "*" in origin
        ):
            raise ValueError("FRONTEND_ORIGINS must contain explicit HTTP(S) origins")
    if not origins:
        raise ValueError("At least one FRONTEND_ORIGINS origin is required")
    secure_value = os.getenv("COOKIE_SECURE", "true").lower()
    if secure_value not in {"true", "false"}:
        raise ValueError("COOKIE_SECURE must be true or false")
    return Settings(
        admin_username=os.getenv("ADMIN_USERNAME", ""),
        admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", ""),
        session_secret=os.getenv("SESSION_SECRET", ""),
        frontend_origins=origins,
        cookie_secure=secure_value == "true",
        admin_access_password=os.getenv("ADMIN_ACCESS_PASSWORD", ""),
    )

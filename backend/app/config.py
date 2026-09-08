"""Application settings loaded from backend/.env."""

import os
from dataclasses import dataclass
from functools import lru_cache


DEVELOPMENT_SESSION_SECRET = "rook-local-development-session-secret"


@dataclass(frozen=True)
class Settings:
    session_secret: str
    frontend_origins: tuple[str, ...]
    cookie_secure: bool
    environment: str = "development"
    admin_username: str = ""
    admin_password_hash: str = ""
    llm_provider: str = "ollama"
    llm_model: str = "granite4.1:3b"
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    pinecone_api_key: str = ""
    pinecone_index: str = "rook"
    pinecone_namespace: str = "documents"
    visitor_session_days: int = 365
    admin_session_seconds: int = 8 * 60 * 60

    @property
    def chat_model(self) -> str:
        return f"{self.llm_provider}:{self.llm_model}"

    @property
    def embeddings(self) -> str:
        return f"{self.embedding_provider}:{self.embedding_model}"


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

    return Settings(
        environment=environment,
        session_secret=session_secret,
        frontend_origins=origins,
        cookie_secure=cookie_secure,
        admin_username=os.getenv("ADMIN_USERNAME", ""),
        admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", ""),
        llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
        llm_model=os.getenv("LLM_MODEL", "granite4.1:3b"),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        pinecone_api_key=os.getenv("PINECONE_API_KEY", ""),
        pinecone_index=os.getenv("PINECONE_INDEX", "rook"),
        pinecone_namespace=os.getenv("PINECONE_NAMESPACE", "documents"),
    )

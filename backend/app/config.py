from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Rook"
    environment: str = "development"
    frontend_origin: str = "http://localhost:5173"
    database_url: str = "postgresql+asyncpg://rook:rook@localhost:5432/rook"

    llm_provider: Literal["openai", "ollama"] = "openai"
    llm_model: str = "gpt-4.1-mini"
    embedding_provider: Literal["openai", "ollama"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""

    pinecone_api_key: str = ""
    pinecone_index: str = "rook"
    pinecone_namespace: str = "documents"
    retrieval_top_k: int = 4

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


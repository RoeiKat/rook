import os
from functools import lru_cache

from langchain_ollama import ChatOllama, OllamaEmbeddings


CHAT_MODEL = "granite4.2:3b"
EMBEDDING_MODEL = "embeddinggemma"


def get_ollama_base_url() -> str:
    """Return the explicitly configured remote Ollama endpoint."""
    value = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise RuntimeError("OLLAMA_BASE_URL is required")
    return value


@lru_cache
def get_chat_model() -> ChatOllama:
    """Return the application chat model configured for the Ollama endpoint."""
    return ChatOllama(
        model=CHAT_MODEL,
        base_url=get_ollama_base_url(),
        temperature=0.5,
        enable_thinking=True,
        reasoning_effort="high",
    )


@lru_cache
def get_embedding_model() -> OllamaEmbeddings:
    """Return the application embedding model configured for the Ollama endpoint."""
    return OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url=get_ollama_base_url(),
        # num_gpu=0, AMD 780m fix for embeddings
    )

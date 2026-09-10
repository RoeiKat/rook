import os
from functools import lru_cache

from langchain_ollama import ChatOllama, OllamaEmbeddings


CHAT_MODEL = "granite4.1:3b"
EMBEDDING_MODEL = "embeddinggemma"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


@lru_cache
def get_chat_model() -> ChatOllama:
    """Return the application chat model configured for the Ollama endpoint."""
    return ChatOllama(
        model=CHAT_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
    )


@lru_cache
def get_embedding_model() -> OllamaEmbeddings:
    """Return the application embedding model configured for the Ollama endpoint."""
    return OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url=OLLAMA_BASE_URL,
        num_gpu=0,
    )

from unittest.mock import patch

import pytest

from app.llm.models import get_chat_model, get_embedding_model


def test_ollama_base_url_is_required(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    get_chat_model.cache_clear()

    with pytest.raises(RuntimeError, match="OLLAMA_BASE_URL is required"):
        get_chat_model()

    get_chat_model.cache_clear()


def test_chat_model_uses_configured_ollama_endpoint(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://inference.example/ollama/")
    get_chat_model.cache_clear()

    with patch("app.llm.models.ChatOllama") as chat_ollama:
        get_chat_model()

    assert chat_ollama.call_args.kwargs["base_url"] == "https://inference.example/ollama"
    get_chat_model.cache_clear()


def test_ollama_api_key_authenticates_chat_and_embedding_clients(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://inference.example/ollama")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-gateway-token")
    get_chat_model.cache_clear()
    get_embedding_model.cache_clear()

    chat_model = get_chat_model()
    embedding_model = get_embedding_model()
    expected = "Bearer test-gateway-token"

    assert chat_model._client._client.headers["authorization"] == expected
    assert chat_model._async_client._client.headers["authorization"] == expected
    assert embedding_model._client._client.headers["authorization"] == expected
    assert embedding_model._async_client._client.headers["authorization"] == expected

    get_chat_model.cache_clear()
    get_embedding_model.cache_clear()

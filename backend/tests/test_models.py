from unittest.mock import patch

import pytest

from app.llm.models import get_chat_model


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

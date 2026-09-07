from unittest.mock import patch

import pytest

from app.config import Settings
from app.llm.embeddings import get_embedding_model
from app.llm.factory import get_chat_model


def test_openai_chat_factory_uses_configured_model():
    settings = Settings(llm_provider="openai", llm_model="test-model", openai_api_key="test")
    with patch("app.llm.factory.get_settings", return_value=settings):
        model = get_chat_model()
    assert model.model_name == "test-model"


def test_unsupported_provider_is_rejected():
    settings = Settings.model_construct(llm_provider="unknown")
    with patch("app.llm.factory.get_settings", return_value=settings):
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_chat_model()


def test_openai_embedding_factory_uses_configured_model():
    settings = Settings(embedding_provider="openai", embedding_model="embed-test", openai_api_key="test")
    with patch("app.llm.embeddings.get_settings", return_value=settings):
        model = get_embedding_model()
    assert model.model == "embed-test"

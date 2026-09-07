from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings


def get_chat_model() -> BaseChatModel:
    settings = get_settings()
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, streaming=True)

    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
        )

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


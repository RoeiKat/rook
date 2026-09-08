import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.agent import model as chat_model
from app.prompts.title import TITLE_PROMPT
from app.agent.titles import fallback_title, generate_title, normalize_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('  Title: "Roei\'s   Python Projects"  ', "Roei's Python Projects"),
        ("\u201cRoei's Python Projects\u201d", "Roei's Python Projects"),
        ("**Roei's Python Projects**", "Roei's Python Projects"),
        ("Roei's **Python** `Projects`", "Roei's Python Projects"),
        ("One\n two\tthree four five six seven", "One two three four five"),
        ("A" * 154 + " four extra", "A" * 154 + " four"),
        ("A" * 160, "A" * 160),
        ("A" * 161 + " projects", None),
        ('{"title": "Python Projects"}', None),
        ("```Python Projects```", None),
        ("<title>Python Projects</title>", None),
        ("\x00Python Projects", None),
        ([], None),
        (None, None),
        (" ", None),
        ("Title: \"\"", None),
        ("Here is the title: Roei's Projects", None),
        ("Sure, here is a concise title", None),
        ("Roei's Python Projects\n\nThis title describes the projects.", None),
        ('"Roei\'s Python Projects".', "Roei's Python Projects"),
        ("... !!!", None),
    ],
)
def test_normalize_title_enforces_plain_text_whole_word_limits(raw, expected):
    title = normalize_title(raw)
    assert title == expected
    if title:
        assert 1 <= len(title.split()) <= 5
        assert len(title) <= 160


async def test_title_uses_tool_free_configured_model_with_separate_prompt():
    model = Mock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content='Title: "Roei\'s Python Projects"'))
    question = "What projects has Roei built with Python?"
    with patch("app.agent.titles.init_chat_model", return_value=model) as initialize:
        assert await generate_title(f"  {question}  ") == "Roei's Python Projects"
    initialize.assert_called_once_with(chat_model)
    model.ainvoke.assert_awaited_once_with(
        [SystemMessage(content=TITLE_PROMPT), HumanMessage(content=question)]
    )
    model.bind_tools.assert_not_called()
    model.astream.assert_not_called()


@pytest.mark.parametrize("question", ["", " ", "\n\t"])
async def test_blank_question_rejected_before_model_call(question):
    with patch("app.agent.titles.init_chat_model") as initialize:
        with pytest.raises(ValueError, match="blank"):
            await generate_title(question)
    initialize.assert_not_called()


@pytest.mark.parametrize("result", ["", "A" * 161, '{"title": "Wrong format"}', "!!!"])
async def test_unusable_model_result_uses_question_fallback(result):
    model = Mock(ainvoke=AsyncMock(return_value=AIMessage(content=result)))
    with patch("app.agent.titles.init_chat_model", return_value=model):
        assert await generate_title("What projects has Roei built with Python?") == "What projects has Roei built"


async def test_model_failure_uses_fallback_without_logging_exception_secrets(caplog):
    model = Mock(ainvoke=AsyncMock(side_effect=RuntimeError("secret-provider-key")))
    with patch("app.agent.titles.init_chat_model", return_value=model):
        assert await generate_title("Python projects") == "Python projects"
    assert "secret-provider-key" not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_model_initialization_failure_does_not_prevent_question_fallback():
    with patch("app.agent.titles.init_chat_model", side_effect=ValueError("Unavailable configuration")):
        assert await generate_title("Python projects") == "Python projects"


async def test_timeout_cancels_title_request_and_uses_fallback(monkeypatch):
    cancelled = asyncio.Event()

    async def delayed_result(*_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr("app.agent.titles.TITLE_TIMEOUT_SECONDS", 0.01)
    model = Mock(ainvoke=AsyncMock(side_effect=delayed_result))
    with patch("app.agent.titles.init_chat_model", return_value=model):
        assert await generate_title("Python projects") == "Python projects"
    assert cancelled.is_set()


async def test_request_cancellation_is_not_swallowed():
    model = Mock(ainvoke=AsyncMock(side_effect=asyncio.CancelledError()))
    with patch("app.agent.titles.init_chat_model", return_value=model):
        with pytest.raises(asyncio.CancelledError):
            await generate_title("Python projects")


@pytest.mark.parametrize("question", ["A" * 161, "... !!!", "<>{}[]"])
def test_fallback_without_usable_words_is_descriptive(question):
    assert fallback_title(question) == "Roei inquiry"


def test_fallback_keeps_whole_words_within_storage_limit():
    question = "Project " + "x" * 154 + " details"
    assert fallback_title(question) == "Project"

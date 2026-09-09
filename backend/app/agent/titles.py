import asyncio
import logging
import re

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.agent import model
from app.prompts.title import TITLE_PROMPT

logger = logging.getLogger(__name__)

TITLE_TIMEOUT_SECONDS = 8.0
MAX_TITLE_WORDS = 5
MAX_TITLE_CHARACTERS = 160
FALLBACK_TITLE = "Roei inquiry"
_OUTER_MARKERS = " \t\r\n\"'`\u201c\u201d\u2018\u2019*#"


def _bounded_words(text: str) -> str | None:
    words: list[str] = []
    for word in text.split()[:MAX_TITLE_WORDS]:
        # A single oversized token cannot be shortened without splitting a word.
        if len(" ".join([*words, word])) > MAX_TITLE_CHARACTERS:
            break
        words.append(word)
    title = " ".join(words)
    return title if any(character.isalnum() for character in title) else None


def normalize_title(value: object) -> str | None:
    """Remove common wrappers and enforce storage limits at word boundaries."""
    if not isinstance(value, str):
        return None
    # Structured output, code fences and control characters are not plain titles.
    if re.search(r"[{}\[\]<>\x00-\x08\x0b\x0c\x0e-\x1f]", value) or "```" in value:
        return None
    if re.search(r"\n\s*\n", value.strip()):
        return None
    text = value.strip()
    # Strip punctuation outside a quoted title before removing its quotes.
    text = re.sub(r"([\"'\u201c\u201d\u2018\u2019])[.!?]+$", r"\1", text)
    text = text.strip(_OUTER_MARKERS)
    text = re.sub(r"^title\s*:\s*", "", text, flags=re.IGNORECASE).strip(_OUTER_MARKERS)
    if re.match(r"^(?:here(?:\s+is|['\u2019]s)\b|sure\b|the\s+title\s+is\b)", text, re.IGNORECASE):
        return None
    # Remove inline emphasis/code markers as well as surrounding formatting.
    text = text.replace("*", "").replace("`", "")
    return _bounded_words(text)


def fallback_title(question: str) -> str:
    # Remove markup wrappers rather than allowing structured content into titles.
    text = re.sub(r"[`*#{}\[\]<>\x00-\x1f]", " ", question).strip(_OUTER_MARKERS)
    return _bounded_words(text) or FALLBACK_TITLE


async def generate_title(question: str) -> str:
    """Generate once before insertion; title failures must never block a chat."""
    question = question.strip()
    if not question:
        raise ValueError("The first question must not be blank")
    fallback = fallback_title(question)
    try:
        async with asyncio.timeout(TITLE_TIMEOUT_SECONDS):
            response = await init_chat_model(model).ainvoke(
                [SystemMessage(content=TITLE_PROMPT), HumanMessage(content=question)]
            )
        title = normalize_title(response.content)
        if title:
            return title
        logger.info("Title generation returned unusable content; using question fallback")
    except Exception as exc:
        # Provider exception messages can contain credentials or request contents.
        logger.warning("Title generation failed (%s); using question fallback", type(exc).__name__)
    return fallback

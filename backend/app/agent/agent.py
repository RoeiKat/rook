from functools import lru_cache

from langchain.agents import create_agent

from app.agent.tools import search_documents
from app.llm.models import get_chat_model
from app.prompts.system import SYSTEM_PROMPT


@lru_cache
def get_agent():
    return create_agent(
        model=get_chat_model(),
        tools=[search_documents],
        system_prompt=SYSTEM_PROMPT,
        name="rook",
    )

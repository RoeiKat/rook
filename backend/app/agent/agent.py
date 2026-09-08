from functools import lru_cache

from langchain.agents import create_agent

from app.agent.tools import search_documents
from app.prompts.system import SYSTEM_PROMPT

model = "ollama:granite4.1:3b"


@lru_cache
def get_agent():
    return create_agent(
        model=model,
        tools=[search_documents],
        system_prompt=SYSTEM_PROMPT,
        name="rook",
    )

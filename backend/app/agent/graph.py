from functools import lru_cache

from langchain.agents import create_agent
from langgraph.graph import END, START, MessagesState, StateGraph

from app.agent.tools import search_documents
from app.llm.factory import get_chat_model
from app.prompts.system import SYSTEM_PROMPT


@lru_cache
def get_agent():
    """Mount the LangChain agent as a subgraph in the application graph."""
    agent = create_agent(
        model=get_chat_model(),
        tools=[search_documents],
        system_prompt=SYSTEM_PROMPT,
        name="rook",
    )

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph.compile()

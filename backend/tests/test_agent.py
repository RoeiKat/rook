from unittest.mock import Mock, patch

from app.agent.graph import get_agent


def test_agent_is_created_with_document_search_tool():
    get_agent.cache_clear()
    model = Mock()

    async def compiled_agent(state):
        return state

    with (
        patch("app.agent.graph.get_chat_model", return_value=model),
        patch("app.agent.graph.create_agent", return_value=compiled_agent) as create,
    ):
        graph = get_agent()

    arguments = create.call_args.kwargs
    assert arguments["model"] is model
    assert [tool.name for tool in arguments["tools"]] == ["search_documents"]
    assert arguments["name"] == "rook"
    assert "agent" in graph.get_graph().nodes
    get_agent.cache_clear()

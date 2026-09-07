from unittest.mock import Mock, patch

from app.agent.agent import get_agent, model


def test_agent_is_created_with_document_search_tool():
    get_agent.cache_clear()
    compiled_agent = Mock()
    with patch("app.agent.agent.create_agent", return_value=compiled_agent) as create:
        assert get_agent() is compiled_agent

    arguments = create.call_args.kwargs
    assert arguments["model"] == model
    assert [tool.name for tool in arguments["tools"]] == ["search_documents"]
    assert arguments["name"] == "rook"
    get_agent.cache_clear()

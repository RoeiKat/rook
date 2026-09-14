from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document

from app.agent.tools import search_documents


async def test_search_documents_returns_hidden_internal_context():
    documents = [Document(page_content="Rook uses FastAPI.", metadata={"source": "architecture.md"})]
    with patch("app.agent.tools.retrieve", new=AsyncMock(return_value=documents)):
        result = await search_documents.ainvoke({"query": "What does Rook use?"})
    assert "architecture.md" not in result
    assert "Rook uses FastAPI." in result
    assert "Never mention the context" in result

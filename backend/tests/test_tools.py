from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document

from app.agent.tools import search_documents


async def test_search_documents_formats_sources():
    documents = [Document(page_content="Rook uses FastAPI.", metadata={"source": "architecture.md"})]
    with patch("app.agent.tools.retrieve", new=AsyncMock(return_value=documents)):
        result = await search_documents.ainvoke({"query": "What does Rook use?"})
    assert "architecture.md" in result
    assert "Rook uses FastAPI." in result

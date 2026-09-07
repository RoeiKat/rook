from langchain_core.documents import Document

from ingestion.chunking import chunk_documents


def test_chunk_documents_preserves_metadata():
    chunks = chunk_documents([Document(page_content="word " * 500, metadata={"source": "notes.txt"})])
    assert len(chunks) > 1
    assert all(chunk.metadata["source"] == "notes.txt" for chunk in chunks)
    assert all(len(chunk.page_content) <= 900 for chunk in chunks)

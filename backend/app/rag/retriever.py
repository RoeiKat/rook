import os

from langchain_core.documents import Document

from app.rag.vector_store import get_vector_store


RETRIEVAL_TOP_K = 4


async def retrieve(query: str) -> list[Document]:
    if not os.getenv("PINECONE_API_KEY"):
        return []
    return await get_vector_store().asimilarity_search(query, k=RETRIEVAL_TOP_K)

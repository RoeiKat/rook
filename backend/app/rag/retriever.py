import os

from langchain_core.documents import Document

from app.rag.vector_store import get_vector_store


async def retrieve(query: str) -> list[Document]:
    if not os.getenv("PINECONE_API_KEY"):
        return []
    top_k = int(os.getenv("RETRIEVAL_TOP_K", "4"))
    return await get_vector_store().asimilarity_search(query, k=top_k)

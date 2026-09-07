from langchain_core.documents import Document

from app.config import get_settings
from app.rag.vector_store import get_vector_store


async def retrieve(query: str) -> list[Document]:
    settings = get_settings()
    if not settings.pinecone_api_key:
        return []
    return await get_vector_store().asimilarity_search(query, k=settings.retrieval_top_k)


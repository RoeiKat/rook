import os

from langchain_core.documents import Document

from app.rag.vector_store import PINECONE_API_KEY_ENV, get_vector_store


RETRIEVAL_TOP_K_ENV = "RETRIEVAL_TOP_K"
DEFAULT_RETRIEVAL_TOP_K = 4
RETRIEVAL_TOP_K = int(os.getenv(RETRIEVAL_TOP_K_ENV, str(DEFAULT_RETRIEVAL_TOP_K)))


async def retrieve(query: str, top_k: int = RETRIEVAL_TOP_K) -> list[Document]:
    """Return the most relevant documents for a query, or none without Pinecone."""
    # Skip retrieval when Pinecone is intentionally not configured.
    if not os.getenv(PINECONE_API_KEY_ENV):
        return []
    # Run Pinecone's asynchronous similarity search with the requested result limit.
    return await get_vector_store().asimilarity_search(query, k=top_k)

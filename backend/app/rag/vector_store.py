from langchain_pinecone import PineconeVectorStore

from app.config import get_settings
from app.llm.embeddings import get_embedding_model


def get_vector_store() -> PineconeVectorStore:
    settings = get_settings()
    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is required for retrieval and ingestion")
    return PineconeVectorStore(
        index_name=settings.pinecone_index,
        embedding=get_embedding_model(),
        namespace=settings.pinecone_namespace,
        pinecone_api_key=settings.pinecone_api_key,
    )


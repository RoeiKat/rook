from langchain.embeddings import init_embeddings
from langchain_pinecone import PineconeVectorStore

from app.config import get_settings

embedding_model = get_settings().embeddings

def get_vector_store() -> PineconeVectorStore:
    settings = get_settings()
    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is required for retrieval and ingestion")
    return PineconeVectorStore(
        index_name=settings.pinecone_index,
        embedding=init_embeddings(settings.embeddings),
        namespace=settings.pinecone_namespace,
        pinecone_api_key=settings.pinecone_api_key,
    )

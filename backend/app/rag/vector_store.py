import os

from langchain_pinecone import PineconeVectorStore
from app.llm.models import get_embedding_model


embedding_model = get_embedding_model()
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "rook")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "documents")


def get_vector_store() -> PineconeVectorStore:
    pinecone_api_key = os.getenv("PINECONE_API_KEY", "")
    if not pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is required for retrieval and ingestion")
    return PineconeVectorStore(
        index_name=PINECONE_INDEX,
        embedding=embedding_model,
        namespace=PINECONE_NAMESPACE,
        pinecone_api_key=pinecone_api_key,
    )

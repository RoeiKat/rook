import os

from langchain.embeddings import init_embeddings
from langchain_pinecone import PineconeVectorStore

embedding_model = "openai:text-embedding-3-small"


def get_vector_store() -> PineconeVectorStore:
    api_key = os.getenv("PINECONE_API_KEY", "")
    if not api_key:
        raise RuntimeError("PINECONE_API_KEY is required for retrieval and ingestion")
    return PineconeVectorStore(
        index_name=os.getenv("PINECONE_INDEX", "rook"),
        embedding=init_embeddings(embedding_model),
        namespace=os.getenv("PINECONE_NAMESPACE", "documents"),
        pinecone_api_key=api_key,
    )

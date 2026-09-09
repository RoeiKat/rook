import os

from langchain.embeddings import init_embeddings
from langchain_pinecone import PineconeVectorStore


embedding_model = "ollama:embeddinggemma"
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "rook")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "documents")


def get_vector_store() -> PineconeVectorStore:
    pinecone_api_key = os.getenv("PINECONE_API_KEY", "")
    if not pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is required for retrieval and ingestion")
    return PineconeVectorStore(
        index_name=PINECONE_INDEX,
        embedding=init_embeddings(embedding_model, num_gpu=0),
        namespace=PINECONE_NAMESPACE,
        pinecone_api_key=pinecone_api_key,
    )

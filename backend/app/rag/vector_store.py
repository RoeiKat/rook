import os

from langchain_pinecone import PineconeVectorStore

from app.llm.models import get_embedding_model


PINECONE_API_KEY_ENV = "PINECONE_API_KEY"
PINECONE_INDEX_ENV = "PINECONE_INDEX"
PINECONE_NAMESPACE_ENV = "PINECONE_NAMESPACE"
DEFAULT_PINECONE_INDEX = "rook"
DEFAULT_PINECONE_NAMESPACE = "documents"

PINECONE_INDEX = os.getenv(PINECONE_INDEX_ENV, DEFAULT_PINECONE_INDEX)
PINECONE_NAMESPACE = os.getenv(PINECONE_NAMESPACE_ENV, DEFAULT_PINECONE_NAMESPACE)


def get_vector_store() -> PineconeVectorStore:
    """Return the configured Pinecone store after validating its API key."""
    # Read the secret at call time so tests and runtime configuration can override it.
    pinecone_api_key = os.getenv(PINECONE_API_KEY_ENV)
    # Fail clearly before constructing a client with missing credentials.
    if not pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is required for retrieval and ingestion")
    # Bind Pinecone to the shared embedding model, index, and namespace.
    return PineconeVectorStore(
        index_name=PINECONE_INDEX,
        embedding=get_embedding_model(),
        namespace=PINECONE_NAMESPACE,
        pinecone_api_key=pinecone_api_key,
    )

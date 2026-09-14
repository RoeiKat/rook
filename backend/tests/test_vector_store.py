from unittest.mock import Mock, patch

import pytest

from app.rag.vector_store import (
    PINECONE_INDEX,
    PINECONE_NAMESPACE,
    embedding_model,
    get_vector_store,
)


def test_vector_store_uses_declared_embedding_model():
    vector_store = Mock()
    with (
        patch.dict(
            "os.environ",
            {
                "PINECONE_API_KEY": "test-key",
            },
        ),
        patch("app.rag.vector_store.PineconeVectorStore", return_value=vector_store) as pinecone,
    ):
        assert get_vector_store() is vector_store

    pinecone.assert_called_once_with(
        index_name=PINECONE_INDEX,
        embedding=embedding_model,
        namespace=PINECONE_NAMESPACE,
        pinecone_api_key="test-key",
    )


def test_vector_store_requires_pinecone_key():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="PINECONE_API_KEY"):
            get_vector_store()

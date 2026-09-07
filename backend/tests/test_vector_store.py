from unittest.mock import Mock, patch

import pytest

from app.rag.vector_store import embedding_model, get_vector_store


def test_vector_store_uses_declared_embedding_model():
    embeddings = Mock()
    vector_store = Mock()
    with (
        patch.dict(
            "os.environ",
            {
                "PINECONE_API_KEY": "test-key",
                "PINECONE_INDEX": "test-index",
                "PINECONE_NAMESPACE": "test-namespace",
            },
        ),
        patch("app.rag.vector_store.init_embeddings", return_value=embeddings) as init,
        patch("app.rag.vector_store.PineconeVectorStore", return_value=vector_store) as pinecone,
    ):
        assert get_vector_store() is vector_store

    init.assert_called_once_with(embedding_model)
    pinecone.assert_called_once_with(
        index_name="test-index",
        embedding=embeddings,
        namespace="test-namespace",
        pinecone_api_key="test-key",
    )


def test_vector_store_requires_pinecone_key():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="PINECONE_API_KEY"):
            get_vector_store()

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.config import get_settings
from ingestion.storage import S3DocumentStorage, validate_document_storage_config


@pytest.fixture
def s3_storage():
    client = MagicMock()
    with patch("ingestion.storage.boto3.client", return_value=client) as factory:
        storage = S3DocumentStorage(
            bucket="rook-documents",
            endpoint_url="https://storage.example",
            region="us-east-2",
            access_key_id="access-key",
            secret_access_key="secret-key",
        )
    return storage, client, factory


def test_s3_storage_saves_reads_deletes_and_lists_objects(s3_storage):
    storage, client, factory = s3_storage
    body = BytesIO(b"rook")
    client.get_object.return_value = {"Body": body}
    paginator = client.get_paginator.return_value
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "z/file.pdf"}, {"Key": "a/file.txt"}]},
        {},
    ]

    storage.save("documents/file.txt", b"rook")
    assert storage.read("documents/file.txt") == b"rook"
    storage.delete("documents/file.txt")

    assert storage.list() == ["a/file.txt", "z/file.pdf"]
    factory.assert_called_once()
    client.put_object.assert_called_once_with(
        Bucket="rook-documents", Key="documents/file.txt", Body=b"rook"
    )
    client.get_object.assert_called_once_with(
        Bucket="rook-documents", Key="documents/file.txt"
    )
    client.delete_object.assert_called_once_with(
        Bucket="rook-documents", Key="documents/file.txt"
    )
    paginator.paginate.assert_called_once_with(Bucket="rook-documents")
    assert body.closed


def test_s3_storage_exists_handles_missing_objects(s3_storage):
    storage, client, _ = s3_storage
    assert storage.exists("documents/file.txt") is True

    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not found"}},
        "HeadObject",
    )
    assert storage.exists("documents/missing.txt") is False


def test_s3_storage_rejects_path_traversal(s3_storage):
    storage, _, _ = s3_storage

    with pytest.raises(ValueError, match="Invalid document storage key"):
        storage.save("../secret.txt", b"secret")


def test_s3_storage_configuration_requires_every_setting(monkeypatch):
    values = {
        "DOCUMENT_STORAGE_PROVIDER": "s3",
        "S3_BUCKET": "rook-documents",
        "AWS_ENDPOINT_URL_S3": "https://storage.example",
        "AWS_REGION": "us-east-2",
        "AWS_ACCESS_KEY_ID": "access-key",
        "AWS_SECRET_ACCESS_KEY": "secret-key",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("S3_BUCKET")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="S3_BUCKET"):
        validate_document_storage_config()

    get_settings.cache_clear()

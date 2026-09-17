from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings


class DocumentStorage(Protocol):
    """Define the storage operations required by document ingestion."""

    # Identify which provider owns a stored document.
    provider: str

    def save(self, key: str, content: bytes) -> None:
        """Persist document bytes under a stable key."""
        ...

    def read(self, key: str) -> bytes:
        """Return the bytes stored under a key."""
        ...

    def delete(self, key: str) -> None:
        """Remove a key when it exists."""
        ...

    def list(self) -> list[str]:
        """List all keys currently held by the provider."""
        ...

    def exists(self, key: str) -> bool:
        """Report whether a key currently exists."""
        ...


def validate_key(key: str) -> str:
    """Normalize a relative storage key and reject path traversal."""
    # Interpret keys as provider-neutral POSIX paths.
    path = PurePosixPath(key)
    # Prevent empty, absolute, Windows-style, or parent-traversing keys.
    if not key or key.startswith(("/", "\\")) or "\\" in key or ".." in path.parts:
        raise ValueError("Invalid document storage key")
    # Return one normalized representation for every provider operation.
    return path.as_posix()


@dataclass
class LocalDocumentStorage:
    """Store original document bytes atomically beneath one local directory."""

    # Hold the configured root for all document content.
    root: Path
    # Record the provider name persisted with document metadata.
    provider: str = "local"

    def __post_init__(self) -> None:
        """Resolve and create the configured local storage root."""
        # Resolve the root once so later containment checks are reliable.
        self.root = self.root.resolve()
        # Ensure the storage directory exists before it is used.
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        """Resolve a validated key beneath the configured storage root."""
        # Combine the normalized key with the local root and resolve it.
        path = (self.root / validate_key(key)).resolve()
        # Reject any path that escapes the configured root.
        if path != self.root and self.root not in path.parents:
            raise ValueError("Invalid document storage key")
        # Return the safe absolute local path.
        return path

    def save(self, key: str, content: bytes) -> None:
        """Atomically save document bytes under a validated key."""
        # Resolve the final destination safely.
        target = self._path(key)
        # Create any document ID and digest directories required by the key.
        target.parent.mkdir(parents=True, exist_ok=True)
        # Track the temporary path so failures can clean it up.
        temporary: str | None = None
        try:
            # Create the temporary file on the destination filesystem.
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                # Remember the temporary name after the handle closes.
                temporary = handle.name
                # Write the complete document payload.
                handle.write(content)
                # Flush Python's file buffer.
                handle.flush()
                # Flush operating-system buffers before publishing the file.
                os.fsync(handle.fileno())
            # Atomically replace any prior file with the completed payload.
            os.replace(temporary, target)
        finally:
            # Remove a leftover temporary file after any failed save.
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def read(self, key: str) -> bytes:
        """Read document bytes from a validated local key."""
        # Resolve and read the complete document file.
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        """Delete a local document if it still exists."""
        try:
            # Resolve and remove the document path.
            self._path(key).unlink()
        except FileNotFoundError:
            # Treat repeated deletion as successful.
            return

    def list(self) -> list[str]:
        """Return sorted provider-neutral keys for all stored documents."""
        # Walk files recursively, omit temporary files, and return relative keys.
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and not path.name.startswith(".tmp")
        )

    def exists(self, key: str) -> bool:
        """Report whether a validated key points to a local file."""
        # Resolve the key safely before checking the filesystem.
        return self._path(key).is_file()


@dataclass
class S3DocumentStorage:
    """Store original documents in a private S3-compatible bucket."""

    bucket: str
    endpoint_url: str
    region: str
    access_key_id: str
    secret_access_key: str
    provider: str = "s3"

    def __post_init__(self) -> None:
        # Neon Object Storage requires SigV4 and path-style bucket addressing.
        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def save(self, key: str, content: bytes) -> None:
        """Persist bytes as one complete object."""
        self.client.put_object(Bucket=self.bucket, Key=validate_key(key), Body=content)

    def read(self, key: str) -> bytes:
        """Read and close an object's response stream."""
        response = self.client.get_object(Bucket=self.bucket, Key=validate_key(key))
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def delete(self, key: str) -> None:
        """Delete an object; repeated S3 deletes are successful."""
        self.client.delete_object(Bucket=self.bucket, Key=validate_key(key))

    def list(self) -> list[str]:
        """Return every object key in stable order."""
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)

    def exists(self, key: str) -> bool:
        """Check object existence without downloading its contents."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=validate_key(key))
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise


@lru_cache
def get_document_storage() -> DocumentStorage:
    """Return the cached document store selected by application settings."""
    settings = get_settings()
    validate_document_storage_config()
    if settings.document_storage_provider == "local":
        return LocalDocumentStorage(Path(settings.document_storage_local_path))
    return S3DocumentStorage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.aws_endpoint_url_s3,
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
    )


def validate_document_storage_config() -> None:
    """Fail clearly when the selected document provider is incomplete."""
    settings = get_settings()
    if settings.document_storage_provider == "local":
        if settings.environment == "production":
            raise ValueError("DOCUMENT_STORAGE_PROVIDER must be s3 in production")
        if not settings.document_storage_local_path.strip():
            raise ValueError("DOCUMENT_STORAGE_LOCAL_PATH is required for local storage")
        return
    if settings.document_storage_provider != "s3":
        raise ValueError("DOCUMENT_STORAGE_PROVIDER must be local or s3")

    required = {
        "S3_BUCKET": settings.s3_bucket,
        "AWS_ENDPOINT_URL_S3": settings.aws_endpoint_url_s3,
        "AWS_REGION": settings.aws_region,
        "AWS_ACCESS_KEY_ID": settings.aws_access_key_id,
        "AWS_SECRET_ACCESS_KEY": settings.aws_secret_access_key,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise ValueError(f"Missing S3 document storage settings: {', '.join(missing)}")

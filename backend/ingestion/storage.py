"""Provider-neutral storage for original knowledge-base document bytes."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.config import get_settings


class DocumentStorage(Protocol):
    provider: str

    def save(self, key: str, content: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def list(self) -> list[str]: ...
    def exists(self, key: str) -> bool: ...


def validate_key(key: str) -> str:
    path = PurePosixPath(key)
    if not key or key.startswith(("/", "\\")) or "\\" in key or ".." in path.parts:
        raise ValueError("Invalid document storage key")
    return path.as_posix()


@dataclass
class LocalDocumentStorage:
    root: Path
    provider: str = "local"

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("Invalid document storage key")
        return path

    def save(self, key: str, content: bytes) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                temporary = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            return

    def list(self) -> list[str]:
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and not path.name.startswith(".tmp")
        )

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


@lru_cache
def get_document_storage() -> DocumentStorage:
    settings = get_settings()
    validate_document_storage_config()
    return LocalDocumentStorage(Path(settings.document_storage_local_path))


def validate_document_storage_config() -> None:
    """Fail clearly when local document storage is not configured."""
    settings = get_settings()
    if not settings.document_storage_local_path.strip():
        raise ValueError("DOCUMENT_STORAGE_LOCAL_PATH is required for local storage")

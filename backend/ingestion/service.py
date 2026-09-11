"""Persistent, retry-safe knowledge-base document and vector synchronization."""

from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from langchain_core.documents import Document
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import IngestionState, KnowledgeDocument
from app.rag.vector_store import get_vector_store
from ingestion.chunking import chunk_documents
from ingestion.loaders import SUPPORTED_EXTENSIONS, load_document_bytes
from ingestion.storage import DocumentStorage, LocalDocumentStorage, get_document_storage

SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")
DOCUMENT_STATUSES = {"pending", "processing", "ready", "failed", "deleting"}


class DocumentConflictError(RuntimeError):
    pass


class IngestionAlreadyRunning(RuntimeError):
    pass


class DocumentOperationError(RuntimeError):
    pass


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sanitize_filename(filename: str) -> str:
    if not filename or filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise ValueError("Filename must not contain a path")
    normalized = unicodedata.normalize("NFKC", filename).strip()
    suffix = Path(normalized).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Only .md, .txt, and .pdf files are supported")
    stem = SAFE_FILENAME.sub("_", Path(normalized).stem).strip(" ._")
    if not stem:
        raise ValueError("Filename must contain a usable name")
    return f"{stem[:220]}{suffix}"


def storage_key(document_id: uuid.UUID, digest: str, filename: str) -> str:
    return f"{document_id}/{digest}/{filename}"


async def save_upload(
    session: AsyncSession,
    filename: str,
    content: bytes,
    storage: DocumentStorage | None = None,
) -> tuple[KnowledgeDocument, bool]:
    storage = storage or get_document_storage()
    safe_name = sanitize_filename(filename)
    digest = content_digest(content)
    existing = await session.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.content_hash == digest
    ))
    if existing:
        if existing.status == "deleting" or not await asyncio.to_thread(storage.exists, existing.storage_key):
            await asyncio.to_thread(storage.save, existing.storage_key, content)
            existing.storage_provider = storage.provider
            existing.status = "pending"
            existing.last_error = None
            existing.size_bytes = len(content)
            await session.commit()
            await session.refresh(existing)
        return existing, False

    document_id = uuid.uuid4()
    key = storage_key(document_id, digest, safe_name)
    await asyncio.to_thread(storage.save, key, content)
    document = KnowledgeDocument(
        id=document_id,
        original_filename=filename,
        storage_provider=storage.provider,
        storage_key=key,
        content_hash=digest,
        size_bytes=len(content),
        status="pending",
    )
    session.add(document)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await asyncio.to_thread(storage.delete, key)
        raise
    await session.refresh(document)
    return document, True


async def replace_upload(
    session: AsyncSession,
    document: KnowledgeDocument,
    filename: str,
    content: bytes,
    storage: DocumentStorage | None = None,
) -> tuple[KnowledgeDocument, bool]:
    storage = storage or get_document_storage()
    safe_name = sanitize_filename(filename)
    digest = content_digest(content)
    if digest == document.content_hash:
        if not await asyncio.to_thread(storage.exists, document.storage_key):
            await asyncio.to_thread(storage.save, document.storage_key, content)
            document.status = "pending"
            document.last_error = None
            await session.commit()
        return document, False

    duplicate = await session.scalar(select(KnowledgeDocument.id).where(
        KnowledgeDocument.content_hash == digest,
        KnowledgeDocument.id != document.id,
    ))
    if duplicate:
        raise DocumentConflictError("This document content already exists")

    old_key = document.storage_key
    new_key = storage_key(document.id, digest, safe_name)
    await asyncio.to_thread(storage.save, new_key, content)
    document.original_filename = filename
    document.storage_provider = storage.provider
    document.storage_key = new_key
    document.content_hash = digest
    document.size_bytes = len(content)
    document.status = "pending"
    document.last_error = None
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        await asyncio.to_thread(storage.delete, new_key)
        raise DocumentConflictError("This document content already exists") from exc
    except Exception:
        await session.rollback()
        await asyncio.to_thread(storage.delete, new_key)
        raise
    await session.refresh(document)
    if old_key != new_key:
        try:
            await asyncio.to_thread(storage.delete, old_key)
        except Exception:
            # The active object is safe; reconciliation removes inactive leftovers.
            pass
    return document, True


def _document_id_from_key(key: str) -> uuid.UUID | None:
    parts = PurePosixPath(key).parts
    if len(parts) < 2:
        return None
    try:
        return uuid.UUID(parts[0])
    except ValueError:
        return None


async def reconcile_local_documents(
    session: AsyncSession, storage: DocumentStorage | None = None
) -> None:
    """Discover local manual changes without trusting browser-supplied paths."""
    storage = storage or get_document_storage()
    if not isinstance(storage, LocalDocumentStorage):
        return
    keys = {
        key for key in await asyncio.to_thread(storage.list)
        if PurePosixPath(key).suffix.lower() in SUPPORTED_EXTENSIONS
    }
    documents = list(await session.scalars(select(KnowledgeDocument)))
    by_id = {document.id: document for document in documents}
    active_keys = {document.storage_key for document in documents}

    for document in documents:
        if document.storage_key not in keys:
            if document.status != "deleting":
                document.status = "deleting"
                document.last_error = "The stored document is missing; vector cleanup is pending."
            continue
        if document.status == "deleting":
            continue
        content = await asyncio.to_thread(storage.read, document.storage_key)
        digest = content_digest(content)
        if digest != document.content_hash:
            duplicate = await session.scalar(select(KnowledgeDocument.id).where(
                KnowledgeDocument.content_hash == digest,
                KnowledgeDocument.id != document.id,
            ))
            if duplicate:
                document.status = "failed"
                document.last_error = "The stored content duplicates another document."
            else:
                document.content_hash = digest
                document.size_bytes = len(content)
                document.status = "pending"
                document.last_error = None

    for key in sorted(keys - active_keys):
        discovered_id = _document_id_from_key(key)
        if discovered_id in by_id:
            await asyncio.to_thread(storage.delete, key)
            continue
        content = await asyncio.to_thread(storage.read, key)
        digest = content_digest(content)
        duplicate = await session.scalar(select(KnowledgeDocument.id).where(
            KnowledgeDocument.content_hash == digest
        ))
        if duplicate:
            await asyncio.to_thread(storage.delete, key)
            continue
        name = sanitize_filename(PurePosixPath(key).name)
        document_id = discovered_id or uuid.uuid4()
        stable_key = storage_key(document_id, digest, name)
        if stable_key != key:
            await asyncio.to_thread(storage.save, stable_key, content)
            await asyncio.to_thread(storage.delete, key)
        session.add(KnowledgeDocument(
            id=document_id,
            original_filename=PurePosixPath(key).name,
            storage_provider=storage.provider,
            storage_key=stable_key,
            content_hash=digest,
            size_bytes=len(content),
            status="pending",
        ))
    await session.commit()


async def knowledge_status(session: AsyncSession) -> dict:
    state = await session.get(IngestionState, 1)
    dirty_count = await session.scalar(
        select(KnowledgeDocument.id).where(or_(
            KnowledgeDocument.status != "ready",
            KnowledgeDocument.last_ingested_hash.is_(None),
            KnowledgeDocument.content_hash != KnowledgeDocument.last_ingested_hash,
        )).limit(1)
    )
    return {
        "dirty": dirty_count is not None,
        "synchronized": dirty_count is None and not bool(state and state.is_running),
        "is_running": bool(state and state.is_running),
        "started_at": state.started_at if state else None,
        "finished_at": state.finished_at if state else None,
        "last_error": state.last_error if state else None,
    }


async def ensure_ingestion_idle(session: AsyncSession) -> None:
    state = await session.get(IngestionState, 1)
    if state and state.is_running:
        raise IngestionAlreadyRunning("An ingestion run is already in progress")


def _prepare_chunks(document: KnowledgeDocument, content: bytes) -> list[Document]:
    loaded = load_document_bytes(document.original_filename, content)
    chunks = chunk_documents(loaded)
    for index, chunk in enumerate(chunks):
        chunk.metadata = {
            "document_id": str(document.id),
            "filename": document.original_filename,
            "storage_key": document.storage_key,
            "content_hash": document.content_hash,
            "chunk_index": index,
        }
    return chunks


def _delete_vectors(document_id: uuid.UUID, vector_store=None) -> None:
    store = vector_store or get_vector_store()
    store.delete(filter={"document_id": {"$eq": str(document_id)}})


def _replace_vectors(document: KnowledgeDocument, chunks: list[Document], vector_store=None) -> None:
    store = vector_store or get_vector_store()
    store.delete(filter={"document_id": {"$eq": str(document.id)}})
    if chunks:
        ids = [
            hashlib.sha256(f"{document.id}:{document.content_hash}:{index}".encode()).hexdigest()
            for index in range(len(chunks))
        ]
        store.add_documents(chunks, ids=ids)


async def delete_document(
    session: AsyncSession,
    document: KnowledgeDocument,
    storage: DocumentStorage | None = None,
    vector_store=None,
) -> None:
    storage = storage or get_document_storage()
    document.status = "deleting"
    document.last_error = None
    await session.commit()
    try:
        if document.last_ingested_hash is not None:
            await asyncio.to_thread(_delete_vectors, document.id, vector_store)
        await asyncio.to_thread(storage.delete, document.storage_key)
        await session.delete(document)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        current = await session.get(KnowledgeDocument, document.id)
        if current:
            current.status = "deleting"
            current.last_error = f"Deletion failed ({type(exc).__name__}); retry is safe."
            await session.commit()
        raise DocumentOperationError("Document deletion could not be completed") from exc


async def _acquire_run(session: AsyncSession) -> None:
    result = await session.execute(
        update(IngestionState)
        .where(IngestionState.id == 1, IngestionState.is_running.is_(False))
        .values(is_running=True, started_at=datetime.now(UTC), finished_at=None, last_error=None)
    )
    await session.commit()
    if result.rowcount != 1:
        raise IngestionAlreadyRunning("An ingestion run is already in progress")


async def ingest_dirty_documents(
    session: AsyncSession,
    storage: DocumentStorage | None = None,
    vector_store=None,
) -> dict[str, int | bool]:
    storage = storage or get_document_storage()
    await _acquire_run(session)
    processed = deleted = failed = 0
    try:
        documents = list(await session.scalars(
            select(KnowledgeDocument).where(or_(
                KnowledgeDocument.status != "ready",
                KnowledgeDocument.last_ingested_hash.is_(None),
                KnowledgeDocument.content_hash != KnowledgeDocument.last_ingested_hash,
            )).order_by(KnowledgeDocument.created_at)
        ))
        for candidate in documents:
            document = await session.get(KnowledgeDocument, candidate.id)
            if document is None:
                continue
            if document.status == "deleting":
                try:
                    await delete_document(session, document, storage, vector_store)
                    deleted += 1
                except DocumentOperationError:
                    failed += 1
                continue
            document.status = "processing"
            document.last_error = None
            await session.commit()
            try:
                content = await asyncio.to_thread(storage.read, document.storage_key)
                chunks = await asyncio.to_thread(_prepare_chunks, document, content)
                await asyncio.to_thread(_replace_vectors, document, chunks, vector_store)
                document.last_ingested_hash = document.content_hash
                document.status = "ready"
                document.last_error = None
                document.ingested_at = datetime.now(UTC)
                await session.commit()
                processed += 1
            except Exception as exc:
                await session.rollback()
                current = await session.get(KnowledgeDocument, candidate.id)
                if current:
                    current.status = "failed"
                    current.last_error = f"Ingestion failed ({type(exc).__name__}); retry is safe."
                    await session.commit()
                failed += 1
    finally:
        state = await session.get(IngestionState, 1)
        if state:
            state.is_running = False
            state.finished_at = datetime.now(UTC)
            state.last_error = f"{failed} document operation(s) failed." if failed else None
            await session.commit()
    status = await knowledge_status(session)
    return {
        "processed": processed,
        "deleted": deleted,
        "failed": failed,
        "dirty": bool(status["dirty"]),
    }

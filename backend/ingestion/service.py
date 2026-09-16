from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from langchain_core.documents import Document
from pinecone.exceptions import NotFoundException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import IngestionState, KnowledgeDocument
from app.rag.vector_store import get_vector_store
from ingestion.chunking import chunk_documents
from ingestion.loaders import SUPPORTED_EXTENSIONS, load_document_bytes
from ingestion.storage import DocumentStorage, LocalDocumentStorage, get_document_storage

SAFE_FILENAME_PATTERN = r"[^A-Za-z0-9._ -]+"
MAX_FILENAME_STEM_LENGTH = 220
CONTENT_HASH_ALGORITHM = "sha256"
INGESTION_STATE_ID = 1
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_DELETING = "deleting"
VECTOR_DOCUMENT_ID_FIELD = "document_id"

SAFE_FILENAME = re.compile(SAFE_FILENAME_PATTERN)
DOCUMENT_STATUSES = {
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_READY,
    STATUS_FAILED,
    STATUS_DELETING,
}


class DocumentConflictError(RuntimeError):
    """Indicate that uploaded content already belongs to another document."""


class IngestionAlreadyRunning(RuntimeError):
    """Indicate that another ingestion run currently holds the run state."""


class DocumentOperationError(RuntimeError):
    """Hide provider details when a document operation fails safely."""


def content_digest(content: bytes) -> str:
    """Return the stable content hash used for deduplication and vector IDs."""
    # Hash the exact uploaded bytes with the declared algorithm.
    return hashlib.new(CONTENT_HASH_ALGORITHM, content).hexdigest()


def sanitize_filename(filename: str) -> str:
    """Validate a supported filename and replace unsafe stem characters."""
    # Accept only a filename, never a client-supplied path.
    if not filename or filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise ValueError("Filename must not contain a path")
    # Normalize Unicode and trim surrounding whitespace.
    normalized = unicodedata.normalize("NFKC", filename).strip()
    # Compare supported extensions case-insensitively.
    suffix = Path(normalized).suffix.lower()
    # Reject file types that existing loaders cannot parse.
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Only .md, .txt, and .pdf files are supported")
    # Replace unsafe characters and strip unusable punctuation from the stem.
    stem = SAFE_FILENAME.sub("_", Path(normalized).stem).strip(" ._")
    # Require at least one safe stem character.
    if not stem:
        raise ValueError("Filename must contain a usable name")
    # Bound the storage filename while preserving its validated extension.
    return f"{stem[:MAX_FILENAME_STEM_LENGTH]}{suffix}"


def storage_key(document_id: uuid.UUID, digest: str, filename: str) -> str:
    """Build the stable provider-neutral key for one document version."""
    # Group originals by document ID and immutable content hash.
    return f"{document_id}/{digest}/{filename}"


async def save_upload(
    session: AsyncSession,
    filename: str,
    content: bytes,
    storage: DocumentStorage | None = None,
) -> tuple[KnowledgeDocument, bool]:
    """Save new content or recover its existing record; report if it was created."""
    # Use injected storage in tests and the configured provider otherwise.
    storage = storage or get_document_storage()
    # Validate the client filename before it becomes part of a storage key.
    safe_name = sanitize_filename(filename)
    # Hash bytes once for deduplication and stable storage layout.
    digest = content_digest(content)
    # Find an existing record with identical content.
    existing = await session.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.content_hash == digest
    ))
    # Return the existing record instead of duplicating identical content.
    if existing:
        # Restore content and queue ingestion when deletion or file loss interrupted it.
        if existing.status == STATUS_DELETING or not await asyncio.to_thread(
            storage.exists, existing.storage_key
        ):
            # Perform blocking storage I/O outside the event loop.
            await asyncio.to_thread(storage.save, existing.storage_key, content)
            # Record which provider now owns the restored original.
            existing.storage_provider = storage.provider
            # Mark restored content for a retry-safe ingestion pass.
            existing.status = STATUS_PENDING
            # Clear the obsolete failure message.
            existing.last_error = None
            # Refresh the stored byte count.
            existing.size_bytes = len(content)
            # Persist the repaired record.
            await session.commit()
            # Reload database-generated fields.
            await session.refresh(existing)
        # Signal that deduplication reused an existing record.
        return existing, False

    # Allocate a stable identity for genuinely new content.
    document_id = uuid.uuid4()
    # Build the managed storage key from identity, digest, and safe filename.
    key = storage_key(document_id, digest, safe_name)
    # Save the original bytes before publishing their database record.
    await asyncio.to_thread(storage.save, key, content)
    # Create metadata for the pending knowledge document.
    document = KnowledgeDocument(
        id=document_id,
        original_filename=filename,
        storage_provider=storage.provider,
        storage_key=key,
        content_hash=digest,
        size_bytes=len(content),
        status=STATUS_PENDING,
    )
    # Stage the new record in the current transaction.
    session.add(document)
    try:
        # Publish the metadata after storage succeeds.
        await session.commit()
    except Exception:
        # Discard the failed database transaction.
        await session.rollback()
        # Remove the unreferenced original file.
        await asyncio.to_thread(storage.delete, key)
        raise
    # Reload generated timestamps and other database-managed values.
    await session.refresh(document)
    # Return the record and indicate that it was newly created.
    return document, True


async def replace_upload(
    session: AsyncSession,
    document: KnowledgeDocument,
    filename: str,
    content: bytes,
    storage: DocumentStorage | None = None,
) -> tuple[KnowledgeDocument, bool]:
    """Replace a document's content while preserving its stable document ID."""
    # Use injected storage in tests and the configured provider otherwise.
    storage = storage or get_document_storage()
    # Validate the replacement filename before building a key.
    safe_name = sanitize_filename(filename)
    # Hash replacement bytes for equality, uniqueness, and key generation.
    digest = content_digest(content)
    # Avoid rewriting or re-ingesting unchanged content.
    if digest == document.content_hash:
        # Restore the original if metadata exists but its file is missing.
        if not await asyncio.to_thread(storage.exists, document.storage_key):
            await asyncio.to_thread(storage.save, document.storage_key, content)
            document.status = STATUS_PENDING
            document.last_error = None
            await session.commit()
        # Report that no new document version was created.
        return document, False

    # Prevent one content hash from belonging to multiple document IDs.
    duplicate = await session.scalar(select(KnowledgeDocument.id).where(
        KnowledgeDocument.content_hash == digest,
        KnowledgeDocument.id != document.id,
    ))
    # Surface an intentional conflict before changing storage.
    if duplicate:
        raise DocumentConflictError("This document content already exists")

    # Retain the previous key until the replacement transaction succeeds.
    old_key = document.storage_key
    # Create a versioned key for the replacement bytes.
    new_key = storage_key(document.id, digest, safe_name)
    # Persist new bytes before updating their database pointer.
    await asyncio.to_thread(storage.save, new_key, content)
    # Update the document metadata to describe the replacement.
    document.original_filename = filename
    document.storage_provider = storage.provider
    document.storage_key = new_key
    document.content_hash = digest
    document.size_bytes = len(content)
    document.status = STATUS_PENDING
    document.last_error = None
    try:
        # Publish the new active version.
        await session.commit()
    except IntegrityError as exc:
        # Roll back a concurrent duplicate-content race.
        await session.rollback()
        # Remove bytes that never became active.
        await asyncio.to_thread(storage.delete, new_key)
        raise DocumentConflictError("This document content already exists") from exc
    except Exception:
        # Roll back any other database failure.
        await session.rollback()
        # Remove the unreferenced replacement bytes.
        await asyncio.to_thread(storage.delete, new_key)
        raise
    # Reload the committed document state.
    await session.refresh(document)
    # Remove the now-inactive prior version when its key changed.
    if old_key != new_key:
        try:
            await asyncio.to_thread(storage.delete, old_key)
        except Exception:
            # The active object is safe; reconciliation removes inactive leftovers.
            pass
    # Report that the existing document now has new content.
    return document, True


def _document_id_from_key(key: str) -> uuid.UUID | None:
    """Extract a document UUID from a managed storage key when possible."""
    # Split the provider-neutral key into path components.
    parts = PurePosixPath(key).parts
    # Managed keys require at least an ID and a following component.
    if len(parts) < 2:
        return None
    try:
        # Interpret the leading path component as the document ID.
        return uuid.UUID(parts[0])
    except ValueError:
        # Treat manually added, non-managed keys as having no stable ID.
        return None


async def reconcile_local_documents(
    session: AsyncSession, storage: DocumentStorage | None = None
) -> None:
    """Reflect manual local-file additions, edits, and removals in PostgreSQL."""
    # Use injected storage in tests and the configured provider otherwise.
    storage = storage or get_document_storage()
    # Reconciliation applies only to inspectable local filesystem storage.
    if not isinstance(storage, LocalDocumentStorage):
        return
    # Lock the singleton run state against concurrent mutations.
    state = await session.scalar(
        select(IngestionState).where(IngestionState.id == INGESTION_STATE_ID).with_for_update()
    )
    # Require the migration-created control record.
    if state is None:
        raise RuntimeError("Ingestion control state is unavailable")
    # Leave files untouched while a synchronization run owns them.
    if state.is_running:
        return
    # Keep only stored files with formats the ingestion pipeline supports.
    keys = {
        key for key in await asyncio.to_thread(storage.list)
        if PurePosixPath(key).suffix.lower() in SUPPORTED_EXTENSIONS
    }
    # Load all known document records for comparison.
    documents = list(await session.scalars(select(KnowledgeDocument)))
    # Index records by stable ID to recognize inactive versions.
    by_id = {document.id: document for document in documents}
    # Track the one active storage key referenced by each record.
    active_keys = {document.storage_key for document in documents}

    # Reconcile every database record against its stored original.
    for document in documents:
        # Queue vector cleanup when an original file has disappeared.
        if document.storage_key not in keys:
            if document.status != STATUS_DELETING:
                document.status = STATUS_DELETING
                document.last_error = "The stored document is missing; vector cleanup is pending."
            continue
        # Preserve an explicit deletion request until ingestion completes it.
        if document.status == STATUS_DELETING:
            continue
        # Read the current local bytes without blocking the event loop.
        content = await asyncio.to_thread(storage.read, document.storage_key)
        # Detect manual edits by comparing hashes.
        digest = content_digest(content)
        # Queue changed content for re-ingestion.
        if digest != document.content_hash:
            # Ensure the edited bytes do not duplicate another document.
            duplicate = await session.scalar(select(KnowledgeDocument.id).where(
                KnowledgeDocument.content_hash == digest,
                KnowledgeDocument.id != document.id,
            ))
            # Mark duplicate manual edits as actionable failures.
            if duplicate:
                document.status = STATUS_FAILED
                document.last_error = "The stored content duplicates another document."
            else:
                # Adopt the new hash and byte count for the active original.
                document.content_hash = digest
                document.size_bytes = len(content)
                document.status = STATUS_PENDING
                document.last_error = None

    # Import or clean every supported file not referenced by a record.
    for key in sorted(keys - active_keys):
        # Recover a stable ID from managed-looking keys.
        discovered_id = _document_id_from_key(key)
        # Delete an inactive version when its document ID is already known.
        if discovered_id in by_id:
            await asyncio.to_thread(storage.delete, key)
            continue
        # Read manually added content for hashing and registration.
        content = await asyncio.to_thread(storage.read, key)
        digest = content_digest(content)
        # Check whether identical content is already registered.
        duplicate = await session.scalar(select(KnowledgeDocument.id).where(
            KnowledgeDocument.content_hash == digest
        ))
        # Delete redundant originals rather than adding duplicate records.
        if duplicate:
            await asyncio.to_thread(storage.delete, key)
            continue
        # Sanitize the discovered basename for its managed key.
        name = sanitize_filename(PurePosixPath(key).name)
        # Reuse a valid discovered ID or allocate one for an unmanaged file.
        document_id = discovered_id or uuid.uuid4()
        # Build the canonical key for the discovered content.
        stable_key = storage_key(document_id, digest, name)
        # Move unmanaged files into the canonical layout through safe storage calls.
        if stable_key != key:
            await asyncio.to_thread(storage.save, stable_key, content)
            await asyncio.to_thread(storage.delete, key)
        # Register the discovered original for the next ingestion run.
        session.add(KnowledgeDocument(
            id=document_id,
            original_filename=PurePosixPath(key).name,
            storage_provider=storage.provider,
            storage_key=stable_key,
            content_hash=digest,
            size_bytes=len(content),
            status=STATUS_PENDING,
        ))
    # Persist all reconciliation changes together.
    await session.commit()


async def knowledge_status(session: AsyncSession) -> dict:
    """Return synchronization and run-state flags for the knowledge base."""
    # Read the singleton ingestion control state.
    state = await session.get(IngestionState, INGESTION_STATE_ID)
    # Stop after finding the first record that differs from its vector state.
    dirty_count = await session.scalar(
        select(KnowledgeDocument.id).where(or_(
            KnowledgeDocument.status != STATUS_READY,
            KnowledgeDocument.last_ingested_hash.is_(None),
            KnowledgeDocument.content_hash != KnowledgeDocument.last_ingested_hash,
        )).limit(1)
    )
    # Include a run-level failure even when document rows look synchronized.
    dirty = dirty_count is not None or bool(state and state.last_error)
    # Return the compact status shape expected by the API.
    return {
        "dirty": dirty,
        "synchronized": not dirty and not bool(state and state.is_running),
        "is_running": bool(state and state.is_running),
        "started_at": state.started_at if state else None,
        "finished_at": state.finished_at if state else None,
        "last_error": state.last_error if state else None,
    }


async def ensure_ingestion_idle(session: AsyncSession) -> None:
    """Lock the run state and reject mutations during active ingestion."""
    # Serialize uploads, replacements, deletions, and filesystem reconciliation.
    # The lock is released by the mutation's commit or request rollback.
    state = await session.scalar(
        select(IngestionState).where(IngestionState.id == INGESTION_STATE_ID).with_for_update()
    )
    # Prevent the caller from mutating a corpus currently being synchronized.
    if state and state.is_running:
        raise IngestionAlreadyRunning("An ingestion run is already in progress")


def _prepare_chunks(document: KnowledgeDocument, content: bytes) -> list[Document]:
    """Load, split, and label one document for deterministic vector storage."""
    # Parse the original bytes using the loader selected by filename.
    loaded = load_document_bytes(document.original_filename, content)
    # Split the loaded pages or text into retrieval-sized chunks.
    chunks = chunk_documents(loaded)
    # Replace loader metadata with stable application metadata for every chunk.
    for index, chunk in enumerate(chunks):
        chunk.metadata = {
            VECTOR_DOCUMENT_ID_FIELD: str(document.id),
            "filename": document.original_filename,
            "storage_key": document.storage_key,
            "content_hash": document.content_hash,
            "chunk_index": index,
        }
    # Return chunks ready for Pinecone insertion.
    return chunks


def _delete_vectors(document_id: uuid.UUID, vector_store=None) -> None:
    """Delete every vector associated with one document ID."""
    # Use an injected test store or create the configured Pinecone store.
    store = vector_store or get_vector_store()
    try:
        # Filter by stable metadata instead of tracking individual chunk IDs.
        store.delete(filter={VECTOR_DOCUMENT_ID_FIELD: {"$eq": str(document_id)}})
    except NotFoundException:
        # Pinecone removes an empty namespace. Deleting from one that no longer
        # exists is already the desired idempotent result.
        return


def _upsert_vectors(document: KnowledgeDocument, chunks: list[Document], vector_store=None) -> None:
    """Insert document chunks under deterministic vector IDs."""
    # Avoid a provider call when a document produced no text chunks.
    if not chunks:
        return
    # Use an injected test store or create the configured Pinecone store.
    store = vector_store or get_vector_store()
    # Human-readable IDs make all chunks for one document easy to group in
    # Pinecone while remaining deterministic and safe to retry.
    ids = [
        f"{document.id}:{document.content_hash}:{index}"
        for index in range(len(chunks))
    ]
    # Insert the chunks and their matching stable IDs together.
    store.add_documents(chunks, ids=ids)


def _replace_vectors(document: KnowledgeDocument, chunks: list[Document], vector_store=None) -> None:
    """Replace all existing vectors for one document with new chunks."""
    # Remove prior content for this stable document identity.
    _delete_vectors(document.id, vector_store)
    # Insert the current content using deterministic IDs.
    _upsert_vectors(document, chunks, vector_store)


def _clear_vector_namespace(vector_store=None) -> None:
    """Delete every vector in the vector store's configured namespace."""
    # Use an injected test store or create the configured Pinecone store.
    store = vector_store or get_vector_store()
    try:
        # Ask Pinecone to remove every vector in the active namespace.
        store.delete(delete_all=True)
    except NotFoundException:
        # A prior rebuild may already have removed the namespace. An absent
        # namespace is equivalent to a successful clear and can be rebuilt.
        return


async def delete_document(
    session: AsyncSession,
    document: KnowledgeDocument,
    storage: DocumentStorage | None = None,
    vector_store=None,
) -> None:
    """Remove a document's vectors, original bytes, and database record safely."""
    # Use injected storage in tests and the configured provider otherwise.
    storage = storage or get_document_storage()
    # Persist deletion intent so interrupted work can be retried.
    document.status = STATUS_DELETING
    document.last_error = None
    await session.commit()
    try:
        # Skip Pinecone when this document has never completed ingestion.
        if document.last_ingested_hash is not None:
            await asyncio.to_thread(_delete_vectors, document.id, vector_store)
        # Remove the stored original without blocking the event loop.
        await asyncio.to_thread(storage.delete, document.storage_key)
        # Remove the metadata after external cleanup succeeds.
        await session.delete(document)
        await session.commit()
    except Exception as exc:
        # Discard partial database changes from the failed attempt.
        await session.rollback()
        # Reload the record because rollback may expire its state.
        current = await session.get(KnowledgeDocument, document.id)
        # Preserve retryable deletion state when the record still exists.
        if current:
            current.status = STATUS_DELETING
            current.last_error = f"Deletion failed ({type(exc).__name__}); retry is safe."
            await session.commit()
        # Raise a stable application error without provider secrets.
        raise DocumentOperationError("Document deletion could not be completed") from exc


async def _acquire_run(session: AsyncSession) -> None:
    """Atomically mark ingestion as running or reject a concurrent run."""
    # Claim the singleton state only when no run currently owns it.
    result = await session.execute(
        update(IngestionState)
        .where(
            IngestionState.id == INGESTION_STATE_ID,
            IngestionState.is_running.is_(False),
        )
        .values(is_running=True, started_at=datetime.now(UTC), finished_at=None, last_error=None)
    )
    # Publish the run claim for competing workers to observe.
    await session.commit()
    # Exactly one updated row means this worker acquired the run.
    if result.rowcount != 1:
        raise IngestionAlreadyRunning("An ingestion run is already in progress")


async def _synchronize_documents(
    session: AsyncSession,
    documents: list[KnowledgeDocument],
    storage: DocumentStorage,
    vector_store=None,
    replace_existing_vectors: bool = True,
) -> tuple[int, int, int]:
    """Synchronize selected records and return processed, deleted, and failed counts."""
    # Start all run counters at zero.
    processed = deleted = failed = 0
    # Process candidates sequentially so each document commits independently.
    for candidate in documents:
        # Reload current state because earlier operations commit the session.
        document = await session.get(KnowledgeDocument, candidate.id)
        # Ignore records removed by another completed operation.
        if document is None:
            continue
        # Finish retryable deletion records instead of ingesting them.
        if document.status == STATUS_DELETING:
            try:
                await delete_document(session, document, storage, vector_store)
                # Count successful metadata, file, and vector removal.
                deleted += 1
            except DocumentOperationError:
                # Keep processing other documents after a safe deletion failure.
                failed += 1
            continue
        # Publish active processing state before external work begins.
        document.status = STATUS_PROCESSING
        document.last_error = None
        await session.commit()
        try:
            # Load the persisted original bytes.
            content = await asyncio.to_thread(storage.read, document.storage_key)
            # Parse, split, and label the source outside the event loop.
            chunks = await asyncio.to_thread(_prepare_chunks, document, content)
            # Rebuilds insert into an already-cleared namespace; normal runs replace.
            vector_operation = _replace_vectors if replace_existing_vectors else _upsert_vectors
            # Apply the selected blocking vector operation in a worker thread.
            await asyncio.to_thread(vector_operation, document, chunks, vector_store)
            # Record exactly which content hash is now represented in Pinecone.
            document.last_ingested_hash = document.content_hash
            document.status = STATUS_READY
            document.last_error = None
            # Timestamp the successful synchronization in UTC.
            document.ingested_at = datetime.now(UTC)
            await session.commit()
            # Count the completed document.
            processed += 1
        except Exception as exc:
            # Discard uncommitted record changes from this attempt.
            await session.rollback()
            # Reload the candidate after rollback.
            current = await session.get(KnowledgeDocument, candidate.id)
            # Persist a retry-safe error without leaking provider details.
            if current:
                current.status = STATUS_FAILED
                current.last_error = f"Ingestion failed ({type(exc).__name__}); retry is safe."
                await session.commit()
            # Count the failure and continue with the remaining corpus.
            failed += 1
    # Return aggregate counts for the API and CLI.
    return processed, deleted, failed


async def _release_run(session: AsyncSession, failed: int, error: str | None = None) -> None:
    """Mark ingestion finished and persist its sanitized summary error."""
    # Reload the singleton state after document-level commits.
    state = await session.get(IngestionState, INGESTION_STATE_ID)
    # A missing control row is already handled by acquisition semantics.
    if state:
        # Release the run for future synchronization requests.
        state.is_running = False
        # Record completion time in UTC.
        state.finished_at = datetime.now(UTC)
        # Prefer a run-level error, then summarize document failures.
        state.last_error = error or (f"{failed} document operation(s) failed." if failed else None)
        # Publish the released state.
        await session.commit()


async def ingest_dirty_documents(
    session: AsyncSession,
    storage: DocumentStorage | None = None,
    vector_store=None,
) -> dict[str, int | bool]:
    """Synchronize all dirty records and return aggregate run results."""
    # Use injected storage in tests and the configured provider otherwise.
    storage = storage or get_document_storage()
    # Prevent concurrent ingestion runs.
    await _acquire_run(session)
    # Initialize counts so the run can always release cleanly.
    processed = deleted = failed = 0
    try:
        # Select records whose database content differs from vector state.
        documents = list(await session.scalars(
            select(KnowledgeDocument).where(or_(
                KnowledgeDocument.status != STATUS_READY,
                KnowledgeDocument.last_ingested_hash.is_(None),
                KnowledgeDocument.content_hash != KnowledgeDocument.last_ingested_hash,
            )).order_by(KnowledgeDocument.created_at)
        ))
        # Synchronize the selected records and collect result counts.
        processed, deleted, failed = await _synchronize_documents(
            session, documents, storage, vector_store
        )
    finally:
        # Release the singleton run state even after an unexpected failure.
        await _release_run(session, failed)
    # Recalculate whether any dirty work remains.
    status = await knowledge_status(session)
    # Return the stable response shape used by the API and CLI.
    return {
        "processed": processed,
        "deleted": deleted,
        "failed": failed,
        "dirty": bool(status["dirty"]),
    }


async def rebuild_knowledge_base(
    session: AsyncSession,
    storage: DocumentStorage | None = None,
    vector_store=None,
) -> dict[str, int | bool]:
    """Clear the configured Pinecone namespace and rebuild it from stored originals."""
    # Use injected storage in tests and the configured provider otherwise.
    storage = storage or get_document_storage()
    # Prevent concurrent rebuild or incremental ingestion runs.
    await _acquire_run(session)
    # Initialize result counters and an optional run-level error.
    processed = deleted = failed = 0
    release_error: str | None = None
    try:
        # Rebuild every known document in deterministic creation order.
        documents = list(await session.scalars(
            select(KnowledgeDocument).order_by(KnowledgeDocument.created_at)
        ))
        # Persist dirty state before the destructive external operation. A crash or
        # provider failure can therefore never leave the UI claiming synchronization.
        for document in documents:
            # Preserve deletion requests; mark all other records for rebuild.
            if document.status != STATUS_DELETING:
                document.status = STATUS_PENDING
                document.last_error = None
        # Publish dirty state before clearing remote vectors.
        await session.commit()
        try:
            # Remove the entire active namespace before re-inserting content.
            await asyncio.to_thread(_clear_vector_namespace, vector_store)
        except Exception as exc:
            # Persist a sanitized run-level failure during release.
            release_error = f"Namespace rebuild failed ({type(exc).__name__}); retry is safe."
            raise DocumentOperationError("Pinecone namespace could not be cleared") from exc
        # Insert all current chunks without redundant per-document deletion.
        processed, deleted, failed = await _synchronize_documents(
            session, documents, storage, vector_store, replace_existing_vectors=False
        )
    finally:
        # Release the run and expose any namespace-level failure.
        await _release_run(session, failed, release_error)
    # Recalculate dirty state after rebuilding the complete corpus.
    status = await knowledge_status(session)
    # Return the stable response shape used by the API.
    return {
        "processed": processed,
        "deleted": deleted,
        "failed": failed,
        "dirty": bool(status["dirty"]),
    }

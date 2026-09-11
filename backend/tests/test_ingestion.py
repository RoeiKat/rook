import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pinecone.exceptions import NotFoundException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.ingestion import router
from app.auth import Identity, require_admin
from app.config import get_settings
from app.database.connection import get_session
from app.database.migrations import migrate_schema
from app.database.models import IngestionState, KnowledgeDocument
from ingestion.service import ingest_dirty_documents
from ingestion.storage import LocalDocumentStorage

CSRF = {"Origin": "http://localhost:5173", "X-CSRF-Protection": "1"}


class MemoryStorage:
    provider = "local"

    def __init__(self):
        self.objects = {}
        self.fail_read = False

    def save(self, key, content):
        self.objects[key] = content

    def read(self, key):
        if self.fail_read:
            raise OSError("private storage details")
        return self.objects[key]

    def delete(self, key):
        self.objects.pop(key, None)

    def list(self):
        return sorted(self.objects)

    def exists(self, key):
        return key in self.objects


class MemoryVectors:
    def __init__(self):
        self.vectors = {}
        self.fail_add = False
        self.fail_clear = False
        self.missing_on_clear = False
        self.deletes = []
        self.clear_count = 0

    def delete(self, filter=None, delete_all=False):
        if delete_all:
            if self.fail_clear:
                raise RuntimeError("private Pinecone details")
            if self.missing_on_clear:
                raise NotFoundException(status=404, reason="namespace not found")
            self.vectors.clear()
            self.clear_count += 1
            return
        document_id = filter["document_id"]["$eq"]
        self.deletes.append(document_id)
        self.vectors = {
            key: value for key, value in self.vectors.items()
            if value.metadata["document_id"] != document_id
        }

    def add_documents(self, documents, ids):
        if self.fail_add:
            raise RuntimeError("private Pinecone details")
        self.vectors.update(dict(zip(ids, documents, strict=True)))


@pytest.fixture
async def ingestion_api(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-with-at-least-32-characters")
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("DOCUMENT_UPLOAD_MAX_BYTES", "32")
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(migrate_schema)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    storage = MemoryStorage()
    vectors = MemoryVectors()

    async def db_session():
        async with sessions() as session:
            yield session

    async def administrator():
        return Identity(uuid.uuid4(), is_admin=True)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = db_session
    app.dependency_overrides[require_admin] = administrator
    monkeypatch.setattr("ingestion.service.get_document_storage", lambda: storage)
    monkeypatch.setattr("ingestion.service.get_vector_store", lambda: vectors)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=CSRF,
    ) as client:
        yield SimpleNamespace(client=client, sessions=sessions, storage=storage, vectors=vectors)

    await engine.dispose()
    get_settings.cache_clear()


async def upload(client, name="notes.txt", content=b"hello rook"):
    return await client.post("/api/ingestion/documents", files={"file": (name, content)})


async def test_anonymous_users_cannot_access_ingestion_routes(ingestion_api):
    ingestion_api.client._transport.app.dependency_overrides.pop(require_admin)
    assert (await ingestion_api.client.get("/api/ingestion/documents")).status_code == 401
    assert (await upload(ingestion_api.client)).status_code == 401


async def test_upload_listing_validation_size_and_idempotency(ingestion_api):
    client = ingestion_api.client
    assert (await client.get("/api/ingestion/documents")).json() == []
    assert (await upload(client, "malware.exe")).status_code == 400
    assert (await upload(client, "../notes.txt")).status_code == 400
    assert (await upload(client, "large.txt", b"x" * 33)).status_code == 413

    first = await upload(client)
    assert first.status_code == 201
    repeated = await upload(client, "copy.txt")
    assert repeated.status_code == 200
    assert repeated.json()["document_id"] == first.json()["document_id"]
    assert len(ingestion_api.storage.objects) == 1
    listing = await client.get("/api/ingestion/documents")
    assert listing.status_code == 200
    assert listing.json()[0]["status"] == "pending"
    assert (await client.get("/api/ingestion/status")).json()["dirty"] is True


async def test_replace_ingest_retry_and_deterministic_vectors(ingestion_api):
    client = ingestion_api.client
    created = (await upload(client, content=b"old content")).json()
    document_id = created["document_id"]
    first_run = await client.post("/api/ingestion/run")
    assert first_run.json() == {"processed": 1, "deleted": 0, "failed": 0, "dirty": False}
    original_ids = set(ingestion_api.vectors.vectors)
    assert original_ids
    assert all(vector_id.startswith(f"{document_id}:") for vector_id in original_ids)
    assert all(chunk.metadata["document_id"] == document_id for chunk in ingestion_api.vectors.vectors.values())
    assert (await client.post("/api/ingestion/run")).json()["processed"] == 0
    assert set(ingestion_api.vectors.vectors) == original_ids

    replaced = await client.put(
        f"/api/ingestion/documents/{document_id}",
        files={"file": ("updated.md", b"new content")},
    )
    assert replaced.status_code == 200
    assert replaced.json()["status"] == "pending"
    assert (await client.get("/api/ingestion/status")).json()["dirty"] is True

    ingestion_api.vectors.fail_add = True
    failed = await client.post("/api/ingestion/run")
    assert failed.json()["failed"] == 1
    listing = (await client.get("/api/ingestion/documents")).json()
    assert listing[0]["status"] == "failed"
    assert listing[0]["last_error"]
    assert failed.json()["dirty"] is True
    assert not ingestion_api.vectors.vectors

    ingestion_api.vectors.fail_add = False
    retry = await client.post("/api/ingestion/run")
    assert retry.json()["processed"] == 1
    assert retry.json()["dirty"] is False
    assert set(ingestion_api.vectors.vectors) != original_ids
    assert all(chunk.metadata["content_hash"] == replaced.json()["content_hash"] for chunk in ingestion_api.vectors.vectors.values())


async def test_storage_failure_does_not_mark_ready_and_concurrent_run_is_rejected(ingestion_api):
    await upload(ingestion_api.client)
    ingestion_api.storage.fail_read = True
    result = await ingestion_api.client.post("/api/ingestion/run")
    assert result.json()["failed"] == 1
    assert (await ingestion_api.client.get("/api/ingestion/documents")).json()[0]["status"] == "failed"

    async with ingestion_api.sessions() as session:
        await session.execute(update(IngestionState).where(IngestionState.id == 1).values(is_running=True))
        await session.commit()
    conflict = await ingestion_api.client.post("/api/ingestion/run")
    assert conflict.status_code == 409


async def test_delete_and_repeated_delete_clean_vectors(ingestion_api):
    created = (await upload(ingestion_api.client)).json()
    await ingestion_api.client.post("/api/ingestion/run")
    assert ingestion_api.vectors.vectors
    path = f"/api/ingestion/documents/{created['document_id']}"
    assert (await ingestion_api.client.delete(path)).status_code == 204
    assert not ingestion_api.vectors.vectors
    assert not ingestion_api.storage.objects
    assert (await ingestion_api.client.delete(path)).status_code == 204
    assert (await ingestion_api.client.get("/api/ingestion/status")).json()["synchronized"] is True


async def test_rebuild_clears_orphans_and_reingests_every_managed_document(ingestion_api):
    created = (await upload(ingestion_api.client)).json()
    ingestion_api.vectors.vectors["legacy-random-id"] = SimpleNamespace(
        metadata={"source": "/app/ingestion/documents/legacy.md"}
    )

    rebuilt = await ingestion_api.client.post("/api/ingestion/rebuild")

    assert rebuilt.status_code == 200
    assert rebuilt.json() == {"processed": 1, "deleted": 0, "failed": 0, "dirty": False}
    assert ingestion_api.vectors.clear_count == 1
    assert ingestion_api.vectors.deletes == []
    assert "legacy-random-id" not in ingestion_api.vectors.vectors
    assert all(
        chunk.metadata["document_id"] == created["document_id"]
        for chunk in ingestion_api.vectors.vectors.values()
    )


async def test_failed_empty_rebuild_stays_dirty_and_can_be_retried(ingestion_api):
    ingestion_api.vectors.vectors["orphan"] = SimpleNamespace(metadata={})
    ingestion_api.vectors.fail_clear = True

    failed = await ingestion_api.client.post("/api/ingestion/rebuild")

    assert failed.status_code == 503
    status = (await ingestion_api.client.get("/api/ingestion/status")).json()
    assert status["dirty"] is True
    assert status["synchronized"] is False
    assert "private Pinecone details" not in status["last_error"]

    ingestion_api.vectors.fail_clear = False
    retry = await ingestion_api.client.post("/api/ingestion/rebuild")
    assert retry.status_code == 200
    assert retry.json()["dirty"] is False
    assert not ingestion_api.vectors.vectors


async def test_rebuild_treats_an_already_missing_namespace_as_cleared(ingestion_api):
    ingestion_api.vectors.missing_on_clear = True

    rebuilt = await ingestion_api.client.post("/api/ingestion/rebuild")

    assert rebuilt.status_code == 200
    assert rebuilt.json() == {"processed": 0, "deleted": 0, "failed": 0, "dirty": False}


def test_local_storage_is_atomic_scoped_and_idempotent(tmp_path):
    storage = LocalDocumentStorage(tmp_path)
    storage.save("document/file.txt", b"first")
    storage.save("document/file.txt", b"second")
    assert storage.read("document/file.txt") == b"second"
    assert storage.list() == ["document/file.txt"]
    assert storage.exists("document/file.txt")
    with pytest.raises(ValueError):
        storage.save("../outside.txt", b"bad")
    storage.delete("document/file.txt")
    storage.delete("document/file.txt")
    assert not storage.exists("document/file.txt")


async def test_service_can_be_called_directly_with_mocks(ingestion_api):
    async with ingestion_api.sessions() as session:
        document = KnowledgeDocument(
            original_filename="direct.txt", storage_provider="local", storage_key="direct.txt",
            content_hash="a" * 64, size_bytes=6, status="pending",
        )
        ingestion_api.storage.objects["direct.txt"] = b"direct"
        session.add(document)
        await session.commit()
        result = await ingest_dirty_documents(session, ingestion_api.storage, ingestion_api.vectors)
        assert result["processed"] == 1
        assert (await session.scalar(select(KnowledgeDocument))).status == "ready"

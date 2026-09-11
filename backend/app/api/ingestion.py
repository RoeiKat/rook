"""Administrator-only document inventory and knowledge-base synchronization API."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin, require_csrf
from app.config import get_settings
from app.database.connection import get_session
from app.database.models import KnowledgeDocument
from ingestion.service import (
    DocumentConflictError,
    DocumentOperationError,
    IngestionAlreadyRunning,
    delete_document,
    ensure_ingestion_idle,
    ingest_dirty_documents,
    knowledge_status,
    reconcile_local_documents,
    rebuild_knowledge_base,
    replace_upload,
    save_upload,
    sanitize_filename,
)
logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/ingestion",
    dependencies=[Depends(require_admin), Depends(require_csrf)],
)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID = Field(validation_alias="id")
    filename: str = Field(validation_alias="original_filename")
    size_bytes: int
    status: str
    content_hash: str
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    ingested_at: datetime | None


class KnowledgeStatusResponse(BaseModel):
    dirty: bool
    synchronized: bool
    is_running: bool
    started_at: datetime | None
    finished_at: datetime | None
    last_error: str | None


class IngestionResult(BaseModel):
    processed: int
    deleted: int
    failed: int
    dirty: bool


async def read_upload(upload: UploadFile) -> tuple[str, bytes]:
    filename = upload.filename or ""
    try:
        sanitize_filename(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    limit = get_settings().document_upload_max_bytes
    content = bytearray()
    while chunk := await upload.read(min(1024 * 1024, limit + 1 - len(content))):
        content.extend(chunk)
        if len(content) > limit:
            raise HTTPException(status_code=413, detail="Document exceeds the configured upload limit")
    if not content:
        raise HTTPException(status_code=400, detail="Document must not be empty")
    return filename, bytes(content)


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(session: AsyncSession = Depends(get_session)):
    try:
        await reconcile_local_documents(session)
        return list(await session.scalars(
            select(KnowledgeDocument).order_by(KnowledgeDocument.created_at)
        ))
    except Exception as exc:
        logger.error("Document inventory failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Document inventory is currently unavailable") from exc


@router.get("/status", response_model=KnowledgeStatusResponse)
async def get_ingestion_status(session: AsyncSession = Depends(get_session)):
    try:
        return await knowledge_status(session)
    except Exception as exc:
        logger.error("Ingestion status failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Ingestion status is currently unavailable") from exc


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    response: Response,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    try:
        await ensure_ingestion_idle(session)
    except IngestionAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    filename, content = await read_upload(file)
    try:
        document, created = await save_upload(session, filename, content)
        if not created:
            response.status_code = 200
        return document
    except (ValueError, DocumentConflictError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Document upload failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Document upload could not be completed") from exc


@router.put("/documents/{document_id}", response_model=DocumentResponse)
async def replace_document(
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    try:
        await ensure_ingestion_idle(session)
    except IngestionAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    document = await session.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    filename, content = await read_upload(file)
    try:
        updated, _ = await replace_upload(session, document, filename, content)
        return updated
    except DocumentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Document replacement failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Document replacement could not be completed") from exc


@router.delete("/documents/{document_id}", status_code=204)
async def remove_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    try:
        await ensure_ingestion_idle(session)
    except IngestionAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    document = await session.get(KnowledgeDocument, document_id)
    if document is None:
        return Response(status_code=204)
    try:
        await delete_document(session, document)
        return Response(status_code=204)
    except DocumentOperationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/run", response_model=IngestionResult)
async def start_ingestion(session: AsyncSession = Depends(get_session)):
    try:
        await reconcile_local_documents(session)
        return await ingest_dirty_documents(session)
    except IngestionAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Ingestion run failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Ingestion could not be completed") from exc


@router.post("/rebuild", response_model=IngestionResult)
async def rebuild_ingestion(session: AsyncSession = Depends(get_session)):
    try:
        await reconcile_local_documents(session)
        return await rebuild_knowledge_base(session)
    except IngestionAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DocumentOperationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Knowledge-base rebuild failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Knowledge-base rebuild could not be completed") from exc

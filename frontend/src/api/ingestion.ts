import { apiFetch } from "./chat";

export type DocumentStatus = "pending" | "processing" | "ready" | "failed" | "deleting";

export interface KnowledgeDocument {
  document_id: string;
  filename: string;
  size_bytes: number;
  status: DocumentStatus;
  content_hash: string;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  ingested_at: string | null;
}

export interface KnowledgeStatus {
  dirty: boolean;
  synchronized: boolean;
  is_running: boolean;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
}

export interface IngestionResult {
  processed: number;
  deleted: number;
  failed: number;
  dirty: boolean;
}

export async function listDocuments(signal?: AbortSignal): Promise<KnowledgeDocument[]> {
  return (await apiFetch("/api/ingestion/documents", { signal })).json();
}

export async function getIngestionStatus(signal?: AbortSignal): Promise<KnowledgeStatus> {
  return (await apiFetch("/api/ingestion/status", { signal })).json();
}

function fileBody(file: File): FormData {
  const body = new FormData();
  body.append("file", file);
  return body;
}

export async function uploadDocument(file: File): Promise<KnowledgeDocument> {
  return (await apiFetch("/api/ingestion/documents", {
    method: "POST",
    body: fileBody(file),
  })).json();
}

export async function replaceDocument(documentId: string, file: File): Promise<KnowledgeDocument> {
  return (await apiFetch(`/api/ingestion/documents/${encodeURIComponent(documentId)}`, {
    method: "PUT",
    body: fileBody(file),
  })).json();
}

export async function deleteDocument(documentId: string): Promise<void> {
  await apiFetch(`/api/ingestion/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}

export async function runIngestion(): Promise<IngestionResult> {
  return (await apiFetch("/api/ingestion/run", { method: "POST" })).json();
}

export async function rebuildKnowledgeBase(): Promise<IngestionResult> {
  return (await apiFetch("/api/ingestion/rebuild", { method: "POST" })).json();
}

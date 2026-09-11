import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { FileText, RefreshCw, Trash2, Upload } from "lucide-react";
import { isAuthenticationError } from "../api/chat";
import {
  deleteDocument,
  getIngestionStatus,
  listDocuments,
  replaceDocument,
  runIngestion,
  uploadDocument,
  type KnowledgeDocument,
  type KnowledgeStatus,
} from "../api/ingestion";

interface Props {
  onAuthenticationFailure: () => void;
}

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const formatTime = (value: string | null) => value
  ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
  : "Never";

export function KnowledgeBase({ onAuthenticationFailure }: Props) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const mounted = useRef(true);

  const handleError = useCallback((failure: unknown) => {
    if (isAuthenticationError(failure)) {
      onAuthenticationFailure();
      return;
    }
    setError(failure instanceof Error ? failure.message : "The request could not be completed.");
  }, [onAuthenticationFailure]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [items, current] = await Promise.all([
      listDocuments(signal),
      getIngestionStatus(signal),
    ]);
    if (!signal?.aborted && mounted.current) {
      setDocuments(items);
      setStatus(current);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    refresh(controller.signal).catch((failure) => {
      if (!controller.signal.aborted) handleError(failure);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, [handleError, refresh]);

  useEffect(() => {
    if (!status?.is_running) return;
    const timer = window.setTimeout(() => {
      refresh().catch(handleError);
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [handleError, refresh, status?.is_running]);

  const perform = async (name: string, operation: () => Promise<string | void>, success: string) => {
    setAction(name);
    setError(null);
    setFeedback(null);
    try {
      const operationFeedback = await operation();
      await refresh();
      if (mounted.current) setFeedback(operationFeedback ?? success);
    } catch (failure) {
      if (mounted.current) {
        await refresh().catch(() => undefined);
        handleError(failure);
      }
    } finally {
      if (mounted.current) setAction(null);
    }
  };

  const upload = () => {
    if (!selectedFile) return;
    void perform("upload", async () => {
      await uploadDocument(selectedFile);
      setSelectedFile(null);
    }, "Document uploaded. The knowledge base is ready to ingest.");
  };

  const replace = (document: KnowledgeDocument, event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    void perform(`replace-${document.document_id}`, async () => {
      await replaceDocument(document.document_id, file);
    }, `${document.filename} was replaced and is ready to ingest.`);
  };

  const ingest = () => void perform("ingest", async () => {
    const result = await runIngestion();
    return result.failed
      ? `Ingestion finished with ${result.failed} failed document operation(s). You can retry safely.`
      : `Knowledge base synchronized. Processed ${result.processed} document(s).`;
  }, "Knowledge base synchronized.");

  const busy = action !== null || Boolean(status?.is_running);

  return (
    <main className="knowledge-page">
      <header className="knowledge-header">
        <div>
          <p className="knowledge-eyebrow">Administrator</p>
          <h1>Knowledge base</h1>
          <p>Manage source documents and synchronize their searchable chunks.</p>
        </div>
        <div className={`sync-state ${status?.dirty ? "is-dirty" : "is-clean"}`} role="status">
          {status?.is_running ? "Processing" : status?.dirty ? "Changes pending" : "Synchronized"}
        </div>
      </header>

      <section className="upload-panel" aria-labelledby="upload-heading">
        <div><h2 id="upload-heading">Upload a document</h2><p>Markdown, text, or PDF. Uploads are stored privately.</p></div>
        <div className="upload-controls">
          <label className="file-picker">
            <Upload size={17} aria-hidden="true" />
            <span>{selectedFile?.name ?? "Choose file"}</span>
            <input aria-label="Choose document" type="file" accept=".md,.txt,.pdf" disabled={busy}
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
          </label>
          <button className="primary-action" disabled={!selectedFile || busy} onClick={upload}>
            {action === "upload" ? "Uploading..." : "Upload"}
          </button>
        </div>
      </section>

      {error && <p className="knowledge-message is-error" role="alert">{error}</p>}
      {feedback && <p className="knowledge-message" role="status">{feedback}</p>}

      <section className="documents-panel" aria-labelledby="documents-heading">
        <div className="documents-heading">
          <div><h2 id="documents-heading">Documents</h2><p>{documents.length} stored document{documents.length === 1 ? "" : "s"}</p></div>
          <button className="ingest-action" disabled={busy || !status?.dirty} onClick={ingest}>
            <RefreshCw size={17} className={busy ? "spin" : ""} aria-hidden="true" />
            {action === "ingest" || status?.is_running ? "Ingesting..." : "Ingest changes"}
          </button>
        </div>

        {loading ? <p className="document-empty" role="status">Loading documents...</p> : documents.length === 0
          ? <p className="document-empty">No documents uploaded yet.</p>
          : <div className="document-list">
            {documents.map((document) => (
              <article className="document-row" key={document.document_id}>
                <FileText size={21} aria-hidden="true" />
                <div className="document-details">
                  <strong>{document.filename}</strong>
                  <span>{formatBytes(document.size_bytes)} · Last ingested: {formatTime(document.ingested_at)}</span>
                  {document.last_error && <span className="document-error" role="alert">{document.last_error}</span>}
                </div>
                <span className={`document-status status-${document.status}`}>{document.status}</span>
                <div className="document-actions">
                  <label className="secondary-action">
                    Replace
                    <input aria-label={`Replace ${document.filename}`} type="file" accept=".md,.txt,.pdf" disabled={busy}
                      onChange={(event) => replace(document, event)} />
                  </label>
                  <button aria-label={`Delete ${document.filename}`} className="danger-action" disabled={busy}
                    onClick={() => void perform(`delete-${document.document_id}`, () => deleteDocument(document.document_id), `${document.filename} was deleted.`)}>
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </div>
              </article>
            ))}
          </div>}
      </section>
    </main>
  );
}

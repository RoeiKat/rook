// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/chat";
import {
  deleteDocument,
  getIngestionStatus,
  listDocuments,
  replaceDocument,
  runIngestion,
  uploadDocument,
  type KnowledgeDocument,
} from "../src/api/ingestion";
import { KnowledgeBase } from "../src/components/KnowledgeBase";

vi.mock("../src/api/ingestion", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/api/ingestion")>(),
  deleteDocument: vi.fn(),
  getIngestionStatus: vi.fn(),
  listDocuments: vi.fn(),
  replaceDocument: vi.fn(),
  runIngestion: vi.fn(),
  uploadDocument: vi.fn(),
}));

const document: KnowledgeDocument = {
  document_id: "document-one",
  filename: "profile.md",
  size_bytes: 2048,
  status: "pending",
  content_hash: "abc",
  last_error: null,
  created_at: "2026-09-10T08:00:00Z",
  updated_at: "2026-09-10T08:00:00Z",
  ingested_at: null,
};

const dirtyStatus = {
  dirty: true, synchronized: false, is_running: false,
  started_at: null, finished_at: null, last_error: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listDocuments).mockResolvedValue([document]);
  vi.mocked(getIngestionStatus).mockResolvedValue(dirtyStatus);
  vi.mocked(uploadDocument).mockResolvedValue(document);
  vi.mocked(replaceDocument).mockResolvedValue(document);
  vi.mocked(deleteDocument).mockResolvedValue(undefined);
  vi.mocked(runIngestion).mockResolvedValue({ processed: 1, deleted: 0, failed: 0, dirty: false });
});

afterEach(cleanup);

describe("knowledge-base administration", () => {
  it("renders dirty state and supports uploading, replacing, deleting, and ingesting", async () => {
    render(<KnowledgeBase onAuthenticationFailure={vi.fn()} />);
    expect(await screen.findByText("profile.md")).toBeTruthy();
    expect(screen.getByText("Changes pending")).toBeTruthy();
    expect(screen.getByText("2.0 KB · Last ingested: Never")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Ingest changes" }) as HTMLButtonElement).disabled).toBe(false);

    const upload = new File(["new"], "new.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Choose document"), { target: { files: [upload] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(uploadDocument).toHaveBeenCalledWith(upload));

    const replacement = new File(["changed"], "profile.md", { type: "text/markdown" });
    fireEvent.change(screen.getByLabelText("Replace profile.md"), { target: { files: [replacement] } });
    await waitFor(() => expect(replaceDocument).toHaveBeenCalledWith(document.document_id, replacement));

    fireEvent.click(screen.getByRole("button", { name: "Delete profile.md" }));
    await waitFor(() => expect(deleteDocument).toHaveBeenCalledWith(document.document_id));

    fireEvent.click(screen.getByRole("button", { name: "Ingest changes" }));
    await waitFor(() => expect(runIngestion).toHaveBeenCalled());
    expect(await screen.findByText(/Knowledge base synchronized/)).toBeTruthy();
  });

  it("disables ingestion while loading, processing, or synchronized and shows failures", async () => {
    let resolve!: (documents: KnowledgeDocument[]) => void;
    vi.mocked(listDocuments).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<KnowledgeBase onAuthenticationFailure={vi.fn()} />);
    expect(screen.getByText("Loading documents...")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Ingest changes" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => resolve([document]));

    vi.mocked(runIngestion).mockRejectedValue(new Error("Ingestion unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Ingest changes" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Ingestion unavailable");

    cleanup();
    vi.mocked(getIngestionStatus).mockResolvedValue({ ...dirtyStatus, dirty: false, synchronized: true });
    render(<KnowledgeBase onAuthenticationFailure={vi.fn()} />);
    await screen.findByText("Synchronized");
    expect((screen.getByRole("button", { name: "Ingest changes" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("returns to login when the administrator session expires", async () => {
    const expired = vi.fn();
    vi.mocked(listDocuments).mockRejectedValue(new ApiError("Unauthorized", 401));
    render(<KnowledgeBase onAuthenticationFailure={expired} />);
    await waitFor(() => expect(expired).toHaveBeenCalledOnce());
    expect(screen.queryByText("Unauthorized")).toBeNull();
  });
});

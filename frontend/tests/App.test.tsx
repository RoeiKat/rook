// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { ApiError, createConversation, getConversation, getSession, listConversations, login, logout, streamChat, type StreamHandlers } from "../src/api/chat";
import type { ConversationDetail } from "../src/types";

vi.mock("../src/api/chat", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/api/chat")>(),
  getSession: vi.fn(), login: vi.fn(), logout: vi.fn(),
  createConversation: vi.fn(), getConversation: vi.fn(),
  listConversations: vi.fn(), streamChat: vi.fn(),
}));

const conversation: ConversationDetail = {
  id: "conversation-one", title: "Roei Python Projects", created_at: "2026-09-08", updated_at: "2026-09-08",
  messages: [{ id: "message-one", role: "assistant", content: "A private answer", created_at: "2026-09-08" }],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function submitMessage(message = "What projects has Roei built?") {
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: message } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
}

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  window.history.replaceState({}, "", "/");
  Element.prototype.scrollIntoView = vi.fn();
  vi.mocked(getSession).mockResolvedValue({ is_admin: false });
  vi.mocked(login).mockResolvedValue({ is_admin: true });
  vi.mocked(logout).mockResolvedValue(undefined);
  vi.mocked(listConversations).mockResolvedValue([conversation]);
  vi.mocked(getConversation).mockResolvedValue(conversation);
  vi.mocked(streamChat).mockImplementation(async (_message, _id, handlers) => {
    handlers.onMetadata(conversation.id, conversation.title);
    handlers.onToken("A streamed answer");
    handlers.onDone?.("stored-answer");
  });
});

afterEach(cleanup);

describe("public chat", () => {
  it("does not fetch administrator history and resets New conversation locally", async () => {
    localStorage.setItem("rook.conversationId", conversation.id);
    render(<App />);
    await screen.findByText("A private answer");
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Unsent draft" } });
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByText("A private answer")).toBeNull();
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe("");
    expect(localStorage.getItem("rook.conversationId")).toBeNull();
    expect(listConversations).not.toHaveBeenCalled();
    expect(createConversation).not.toHaveBeenCalled();
    expect(streamChat).not.toHaveBeenCalled();
    expect(screen.queryByRole("navigation", { name: "Conversations" })).toBeNull();
    expect(screen.queryByText("Sign in")).toBeNull();
  });

  it("creates on first send, displays metadata title, and includes the ID on follow-ups", async () => {
    render(<App />);
    submitMessage();
    await screen.findByText("A streamed answer");
    await waitFor(() => expect((screen.getByRole("button", { name: "New conversation" }) as HTMLButtonElement).disabled).toBe(false));
    expect(streamChat).toHaveBeenNthCalledWith(1, "What projects has Roei built?", null, expect.any(Object), expect.any(AbortSignal));
    expect(screen.getByRole("heading", { name: conversation.title })).toBeTruthy();
    expect(localStorage.getItem("rook.conversationId")).toBe(conversation.id);
    submitMessage("Tell me more");
    await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(2));
    expect(vi.mocked(streamChat).mock.calls[1][1]).toBe(conversation.id);
    expect(listConversations).not.toHaveBeenCalled();
    expect(createConversation).not.toHaveBeenCalled();
  });

  it("shows loading before metadata and prevents resets and duplicate sends during a stream", async () => {
    const pending = deferred<void>();
    vi.mocked(streamChat).mockReturnValue(pending.promise);
    render(<App />);
    submitMessage();
    expect(screen.getByText("Responding...")).toBeTruthy();
    expect((screen.getByRole("button", { name: "New conversation" }) as HTMLButtonElement).disabled).toBe(true);
    submitMessage("Second question");
    expect(streamChat).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve());
  });

  it("clears inaccessible remembered IDs and allows a fresh first message", async () => {
    localStorage.setItem("rook.conversationId", "other-session-id");
    vi.mocked(getConversation).mockRejectedValue(new ApiError("Not found", 404));
    render(<App />);
    await screen.findByRole("alert");
    expect(localStorage.getItem("rook.conversationId")).toBeNull();
    expect(screen.queryByText("A private answer")).toBeNull();
    submitMessage();
    await waitFor(() => expect(streamChat).toHaveBeenCalled());
    expect(vi.mocked(streamChat).mock.calls[0][1]).toBeNull();
    expect(listConversations).not.toHaveBeenCalled();
  });

  it("ignores stale stream metadata and tokens after unmount", async () => {
    const pending = deferred<void>();
    let handlers!: StreamHandlers;
    vi.mocked(streamChat).mockImplementation((_message, _id, callbacks) => { handlers = callbacks; return pending.promise; });
    const view = render(<App />);
    submitMessage();
    view.unmount();
    expect(vi.mocked(streamChat).mock.calls[0][3]?.aborted).toBe(true);
    await act(async () => {
      handlers.onMetadata("late-conversation", "Late title");
      handlers.onToken("Late token");
      pending.resolve();
    });
    expect(localStorage.getItem("rook.conversationId")).toBeNull();
  });
});

describe("administrator history", () => {
  beforeEach(() => window.history.replaceState({}, "", "/admin"));

  it("waits for server-validated administrator state before fetching history", async () => {
    const pending = deferred<{ is_admin: boolean }>();
    vi.mocked(getSession).mockReturnValue(pending.promise);
    render(<App />);
    expect(screen.getByRole("status").textContent).toBe("Checking session...");
    expect(listConversations).not.toHaveBeenCalled();
    expect(screen.queryByText(conversation.title)).toBeNull();
    await act(async () => pending.resolve({ is_admin: true }));
    fireEvent.click(await screen.findByRole("button", { name: conversation.title }));
    await screen.findByText("A private answer");
    expect(localStorage.getItem("rook.conversationId")).toBeNull();
  });

  it("logs in using credentials and checks the resulting session before listing", async () => {
    vi.mocked(getSession).mockResolvedValueOnce({ is_admin: false }).mockResolvedValue({ is_admin: true });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "Roei" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("button", { name: conversation.title });
    expect(login).toHaveBeenCalledWith("Roei", "test-password");
    expect(getSession).toHaveBeenCalledTimes(1);
    expect(localStorage.length).toBe(0);
  });

  it("does not trust login success without a verified administrator session", async () => {
    vi.mocked(login).mockResolvedValue({ is_admin: false });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "Roei" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("alert");
    expect(listConversations).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
  });

  it("clears history immediately on logout and ignores a late detail response", async () => {
    vi.mocked(getSession).mockResolvedValue({ is_admin: true });
    const pendingDetail = deferred<ConversationDetail>();
    const pendingLogout = deferred<void>();
    vi.mocked(getConversation).mockReturnValue(pendingDetail.promise);
    vi.mocked(logout).mockReturnValue(pendingLogout.promise);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: conversation.title }));
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByLabelText("Username")).toBeTruthy();
    expect(screen.queryByText(conversation.title)).toBeNull();
    expect(vi.mocked(getConversation).mock.calls[0][1]?.aborted).toBe(true);
    await act(async () => { pendingDetail.resolve(conversation); pendingLogout.resolve(); });
    expect(window.location.pathname).toBe("/admin");
    expect(screen.queryByText("A private answer")).toBeNull();
    expect(screen.queryByText(conversation.title)).toBeNull();
  });

  it("returns to login on an administrator 401", async () => {
    vi.mocked(getSession).mockResolvedValue({ is_admin: true });
    vi.mocked(listConversations).mockRejectedValue(new ApiError("Unauthorized", 401));
    render(<App />);
    await screen.findByLabelText("Username");
    expect(screen.getByRole("alert").textContent).toContain("session has ended");
    expect(screen.queryByRole("navigation", { name: "Conversations" })).toBeNull();
  });
});

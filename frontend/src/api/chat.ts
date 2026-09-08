import type { Conversation, ConversationDetail } from "../types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export function isAuthenticationError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes((options.method ?? "GET").toUpperCase())) {
    headers.set("X-CSRF-Protection", "1");
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers, credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`;
    throw new ApiError(detail, response.status);
  }
  return response;
}



export interface AuthSession {
  is_admin: boolean;
}

export async function checkAdminAccess(signal?: AbortSignal): Promise<void> {
  await apiFetch("/api/auth/access", { signal });
}

export async function unlockAdminAccess(password: string, signal?: AbortSignal): Promise<void> {
  await apiFetch("/api/auth/access", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }), signal,
  });
}

export async function getSession(signal?: AbortSignal): Promise<AuthSession> {
  return (await apiFetch("/api/auth/session", { signal })).json();
}

export async function login(username: string, password: string, signal?: AbortSignal): Promise<void> {
  await apiFetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    signal,
  });
}

export async function logout(): Promise<void> {
  await apiFetch("/api/auth/logout", { method: "POST" });
}

export async function listConversations(signal?: AbortSignal): Promise<Conversation[]> {
  return (await apiFetch("/api/conversations", { signal })).json();
}

export async function getConversation(id: string, signal?: AbortSignal): Promise<ConversationDetail> {
  return (await apiFetch(`/api/conversations/${encodeURIComponent(id)}`, { signal })).json();
}

export async function createConversation(message: string, signal?: AbortSignal): Promise<Conversation> {
  return (await apiFetch("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  })).json();
}

export interface StreamHandlers {
  onMetadata: (conversationId: string, title: string) => void;
  onToken: (token: string) => void;
  onDone?: (messageId: string) => void;
}

export async function streamChat(
  message: string,
  conversationId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId, message }),
    signal,
  });
  if (!response.body) throw new Error("Streaming is not supported by this browser");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamError: Error | null = null;
  let completed = false;

  const processEvent = (block: string) => {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    const value = data.join("\n");
    if (event === "metadata") {
      const metadata = JSON.parse(value);
      handlers.onMetadata(metadata.conversation_id, metadata.title);
    }
    if (event === "token") handlers.onToken(JSON.parse(value));
    if (event === "error") streamError = new Error(JSON.parse(value).message);
    if (event === "done") {
      completed = true;
      handlers.onDone?.(JSON.parse(value).message_id);
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? "";
      blocks.forEach(processEvent);
      if (streamError) throw streamError;
      if (done) break;
    }
    if (buffer.trim()) processEvent(buffer);
    if (streamError) throw streamError;
    if (!completed) throw new Error("The response ended before it finished. Please try again.");
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

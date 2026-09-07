import type { Conversation, ConversationDetail } from "../types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

async function ensureOk(response: Response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response;
}

export async function listConversations(): Promise<Conversation[]> {
  return (await ensureOk(await fetch(`${API_BASE}/api/conversations`))).json();
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return (await ensureOk(await fetch(`${API_BASE}/api/conversations/${id}`))).json();
}

export async function createConversation(): Promise<Conversation> {
  return (
    await ensureOk(
      await fetch(`${API_BASE}/api/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New conversation" }),
      }),
    )
  ).json();
}

interface StreamHandlers {
  onMetadata: (conversationId: string) => void;
  onToken: (token: string) => void;
}

export async function streamChat(
  message: string,
  conversationId: string | null,
  handlers: StreamHandlers,
): Promise<void> {
  const response = await ensureOk(
    await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, message }),
    }),
  );
  if (!response.body) throw new Error("Streaming is not supported by this browser");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamError: Error | null = null;

  const processEvent = (block: string) => {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    const value = data.join("\n");
    if (event === "metadata") handlers.onMetadata(JSON.parse(value).conversation_id);
    if (event === "token") handlers.onToken(JSON.parse(value));
    if (event === "error") streamError = new Error(JSON.parse(value).message);
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    blocks.forEach(processEvent);
    if (streamError) throw streamError;
    if (done) break;
  }
  if (buffer.trim()) processEvent(buffer);
  if (streamError) throw streamError;
}

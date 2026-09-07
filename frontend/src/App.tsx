import { useEffect, useState } from "react";
import { createConversation, getConversation, listConversations, streamChat } from "./api/chat";
import { ChatWindow } from "./components/ChatWindow";
import { ConversationSidebar } from "./components/ConversationSidebar";
import type { Conversation, Message } from "./types";

const draftMessage = (role: Message["role"], content: string): Message => ({
  id: crypto.randomUUID(), role, content, created_at: new Date().toISOString(),
});

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(() => localStorage.getItem("rook.conversationId"));
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const refreshConversations = async () => setConversations(await listConversations());

  useEffect(() => {
    refreshConversations().catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!currentId) { setMessages([]); return; }
    localStorage.setItem("rook.conversationId", currentId);
    getConversation(currentId)
      .then((conversation) => setMessages(conversation.messages))
      .catch((err) => { setError(err.message); setCurrentId(null); localStorage.removeItem("rook.conversationId"); });
  }, [currentId]);

  const startConversation = async () => {
    try {
      setError(null);
      const conversation = await createConversation();
      setConversations((items) => [conversation, ...items]);
      setCurrentId(conversation.id);
      setMessages([]);
      setSidebarOpen(false);
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to create conversation"); }
  };

  const sendMessage = async (content: string) => {
    setError(null);
    setLoading(true);
    const assistantId = crypto.randomUUID();
    setMessages((items) => [...items, draftMessage("user", content), { ...draftMessage("assistant", ""), id: assistantId }]);
    try {
      await streamChat(content, currentId, {
        onMetadata: (id) => setCurrentId(id),
        onToken: (token) => setMessages((items) => items.map((item) => item.id === assistantId ? { ...item, content: item.content + token } : item)),
      });
      await refreshConversations();
    } catch (err) {
      setMessages((items) => items.filter((item) => item.id !== assistantId));
      setError(err instanceof Error ? err.message : "Unable to send message");
    } finally { setLoading(false); }
  };

  const current = conversations.find((item) => item.id === currentId);
  return (
    <div className="flex h-dvh overflow-hidden">
      <ConversationSidebar conversations={conversations} currentId={currentId} open={sidebarOpen} onClose={() => setSidebarOpen(false)} onNew={startConversation} onSelect={setCurrentId} />
      <ChatWindow title={current?.title ?? "New conversation"} messages={messages} loading={loading} error={error} onOpenSidebar={() => setSidebarOpen(true)} onSend={sendMessage} />
    </div>
  );
}

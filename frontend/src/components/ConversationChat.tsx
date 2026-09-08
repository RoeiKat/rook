import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getConversation, isAuthenticationError, listConversations, streamChat } from "../api/chat";
import type { Conversation, Message } from "../types";
import { ChatWindow } from "./ChatWindow";
import { ConversationSidebar } from "./ConversationSidebar";

const STORAGE_KEY = "rook.conversationId";
const draftMessage = (role: Message["role"], content: string): Message => ({
  id: crypto.randomUUID(), role, content, created_at: new Date().toISOString(),
});
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "An unexpected error occurred";

interface Props {
  administrator?: boolean;
  checkingSession?: boolean;
  onAuthenticationFailure?: () => void;
  onLogout?: () => void;
}

export function ConversationChat({ administrator = false, checkingSession = false, onAuthenticationFailure, onLogout }: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [title, setTitle] = useState("Rook");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [composerVersion, setComposerVersion] = useState(0);
  const requestVersion = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const busy = useRef(false);

  const handleFailure = useCallback((failure: unknown) => {
    if (administrator && isAuthenticationError(failure)) {
      onAuthenticationFailure?.();
    } else {
      setError(errorMessage(failure));
    }
  }, [administrator, onAuthenticationFailure]);

  const clearDraft = () => {
    setCurrentId(null);
    setTitle("Rook");
    setMessages([]);
    setComposerVersion((version) => version + 1);
    if (!administrator) localStorage.removeItem(STORAGE_KEY);
  };

  const openConversation = useCallback(async (id: string) => {
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const isCurrent = () => version === requestVersion.current && !controller.signal.aborted;
    busy.current = true;
    setLoading(true);
    setError(null);
    setMessages([]);
    setCurrentId(id);
    setTitle("Rook");
    setComposerVersion((value) => value + 1);
    try {
      const conversation = await getConversation(id, controller.signal);
      if (!isCurrent()) return;
      setMessages(conversation.messages);
      setTitle(conversation.title);
      if (!administrator) localStorage.setItem(STORAGE_KEY, id);
    } catch (failure) {
      if (!isCurrent()) return;
      setCurrentId(null);
      if (!administrator) localStorage.removeItem(STORAGE_KEY);
      if (failure instanceof ApiError && failure.status === 404) {
        setError("This conversation is no longer available. Start a new conversation.");
      } else {
        handleFailure(failure);
      }
    } finally {
      if (isCurrent()) {
        busy.current = false;
        setLoading(false);
      }
    }
  }, [administrator, handleFailure]);

  useEffect(() => {
    const controller = new AbortController();
    if (administrator) {
      listConversations(controller.signal).then((items) => {
        if (!controller.signal.aborted) setConversations(items);
      }).catch((failure) => {
        if (!controller.signal.aborted) handleFailure(failure);
      });
    } else {
      const savedId = localStorage.getItem(STORAGE_KEY);
      if (savedId) void openConversation(savedId);
    }
    return () => {
      controller.abort();
      activeRequest.current?.abort();
      requestVersion.current += 1;
    };
  }, [administrator, handleFailure, openConversation]);

  const startConversation = () => {
    if (busy.current) return;
    requestVersion.current += 1;
    activeRequest.current?.abort();
    clearDraft();
    setError(null);
    setSidebarOpen(false);
  };

  const sendMessage = async (content: string) => {
    if (busy.current || !content.trim()) return;
    busy.current = true;
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const isCurrent = () => version === requestVersion.current && !controller.signal.aborted;
    setError(null);
    setLoading(true);
    const assistant = draftMessage("assistant", "");
    let storedMessageId: string | undefined;
    setMessages((items) => [...items, draftMessage("user", content), assistant]);
    try {
      await streamChat(content, currentId, {
        onMetadata: (id, persistedTitle) => {
          if (!isCurrent()) return;
          setCurrentId(id);
          setTitle(persistedTitle);
          if (!administrator) localStorage.setItem(STORAGE_KEY, id);
        },
        onToken: (token) => {
          if (!isCurrent()) return;
          setMessages((items) => items.map((item) => item.id === assistant.id ? { ...item, content: item.content + token } : item));
        },
        onDone: (id) => { storedMessageId = id; },
      }, controller.signal);
      if (!isCurrent()) return;
      if (storedMessageId) {
        setMessages((items) => items.map((item) => item.id === assistant.id ? { ...item, id: storedMessageId! } : item));
      }
      if (administrator) {
        try {
          const items = await listConversations(controller.signal);
          if (isCurrent()) setConversations(items);
        } catch (failure) {
          if (isCurrent()) handleFailure(failure);
        }
      }
    } catch (failure) {
      if (!isCurrent()) return;
      if (failure instanceof ApiError && failure.status === 404) {
        clearDraft();
        setError("This conversation is no longer available. Start a new conversation.");
      } else {
        setMessages((items) => items.filter((item) => item.id !== assistant.id));
        handleFailure(failure);
      }
    } finally {
      if (isCurrent()) {
        busy.current = false;
        setLoading(false);
      }
    }
  };

  if (checkingSession) return <main className="session-loading"><p role="status">Checking session...</p></main>;

  return (
    <div className="conversation-layout">
      <ConversationSidebar conversations={conversations} showHistory={administrator} currentId={currentId} open={sidebarOpen} disabled={loading} onClose={() => setSidebarOpen(false)} onSelect={openConversation} onLogout={onLogout} />
      <ChatWindow title={title} messages={messages} loading={loading} error={error} composerVersion={composerVersion} administrator={administrator} onOpenSidebar={() => setSidebarOpen(true)} onNew={startConversation} onSend={sendMessage} />
    </div>
  );
}

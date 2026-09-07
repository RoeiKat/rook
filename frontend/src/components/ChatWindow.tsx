import type { Message } from "../types";
import { MessageInput } from "./MessageInput";
import { MessageList } from "./MessageList";
import { SidebarTrigger } from "./ConversationSidebar";

interface Props {
  title: string;
  messages: Message[];
  loading: boolean;
  error: string | null;
  onOpenSidebar: () => void;
  onSend: (message: string) => void;
}

export function ChatWindow({ title, messages, loading, error, onOpenSidebar, onSend }: Props) {
  return (
    <main className="flex min-w-0 flex-1 flex-col bg-stone-50">
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-stone-200 px-4 md:px-6">
        <SidebarTrigger onClick={onOpenSidebar} />
        <h2 className="truncate text-sm font-medium text-stone-700">{title}</h2>
        {loading && <span className="ml-auto text-xs text-stone-500">Responding...</span>}
      </header>
      <MessageList messages={messages} loading={loading} />
      <div className="shrink-0 px-4 pb-5 pt-3">
        {error && <div role="alert" className="mx-auto mb-3 max-w-3xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <MessageInput disabled={loading} onSend={onSend} />
      </div>
    </main>
  );
}

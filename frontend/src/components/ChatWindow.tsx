import { useId, useRef, useState } from "react";
import { Info, Plus } from "lucide-react";
import type { Message } from "../types";
import { MessageInput } from "./MessageInput";
import { MessageList } from "./MessageList";
import { SidebarTrigger } from "./ConversationSidebar";
import { Welcome } from "./Welcome";

export const INFO_TEXT = "Insert text here";

function InfoButton() {
  const [open, setOpen] = useState(false);
  const id = useId();
  const pointerFocused = useRef(false);
  return <div className="info-control" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
    <button className="icon-button" aria-label="About Rook" aria-describedby={open ? id : undefined}
      onPointerDown={() => { pointerFocused.current = true; }}
      onFocus={() => { if (!pointerFocused.current) setOpen(true); }}
      onBlur={() => { pointerFocused.current = false; setOpen(false); }}
      onClick={() => { setOpen(true); pointerFocused.current = false; }}
      onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setOpen(false); } }}>
      <Info size={20} strokeWidth={1.6} aria-hidden="true" />
    </button>
    {open && <div role="tooltip" id={id} className="info-tooltip">{INFO_TEXT}</div>}
  </div>;
}

interface Props {
  title: string;
  messages: Message[];
  loading: boolean;
  error: string | null;
  composerVersion?: number;
  administrator?: boolean;
  onOpenSidebar: () => void;
  onNew: () => void;
  onSend: (message: string) => void;
}

export function ChatWindow({ title, messages, loading, error, composerVersion, administrator, onOpenSidebar, onNew, onSend }: Props) {
  const empty = messages.length === 0;
  const composer = <div className="composer-area">
    {error && <div role="alert" className="error-message">{error}</div>}
    <MessageInput key={composerVersion} disabled={loading} onSend={onSend} />
  </div>;
  return <main className="chat-window">
    <header className="chat-header">
      {administrator && <SidebarTrigger onClick={onOpenSidebar} />}
      {!empty && <h2 className="conversation-title">{title}</h2>}
      <div className="header-actions">
        <button className="new-conversation" disabled={loading} onClick={onNew}>
          <Plus size={17} aria-hidden="true" /><span>New conversation</span>
        </button>
        <InfoButton />
      </div>
    </header>
    {empty ? <div className="welcome-area"><Welcome />{composer}</div> : <>
      <MessageList messages={messages} loading={loading} />
      <div className="active-composer">
        <div className="response-status" role="status">{loading ? "Responding..." : ""}</div>
        {composer}
      </div>
    </>}
  </main>;
}

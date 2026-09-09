import { Menu, MessageSquare, X } from "lucide-react";
import type { Conversation } from "../types";

interface Props {
  conversations: Conversation[];
  currentId: string | null;
  open: boolean;
  showHistory?: boolean;
  disabled?: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onLogout?: () => void;
}

export function ConversationSidebar({ conversations, currentId, open, showHistory = false, disabled = false, onClose, onSelect, onLogout }: Props) {
  if (!showHistory) return null;
  return <>
    {open && <button aria-label="Close navigation" className="sidebar-overlay" onClick={onClose} />}
    <aside className={`history-sidebar ${open ? "is-open" : ""}`}>
      <div className="history-heading"><span>Conversations</span>
        <button className="icon-button sidebar-close" onClick={onClose} aria-label="Close sidebar"><X size={19} aria-hidden="true" /></button>
      </div>
      <nav aria-label="Conversations">
        {conversations.map((conversation) => <button key={conversation.id} disabled={disabled}
          aria-current={currentId === conversation.id ? "page" : undefined}
          className="history-item" onClick={() => { onSelect(conversation.id); onClose(); }}>
          <MessageSquare size={16} aria-hidden="true" /><span>{conversation.title}</span>
        </button>)}
      </nav>
      {onLogout && <button onClick={onLogout} className="sign-out">Sign out</button>}
    </aside>
  </>;
}

export function SidebarTrigger({ onClick }: { onClick: () => void }) {
  return <button className="icon-button sidebar-trigger" onClick={onClick} aria-label="Open sidebar"><Menu size={20} aria-hidden="true" /></button>;
}

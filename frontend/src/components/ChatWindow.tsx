import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, Info, Menu, MessageSquare, Plus, X } from "lucide-react";
import type { Message } from "../types";
import { MessageInput } from "./MessageInput";
import { MessageList } from "./MessageList";
import { SidebarTrigger } from "./ConversationSidebar";
import { RookLogo } from "./RookLogo";
import { ThemeToggle } from "./ThemeToggle";
import { Welcome } from "./Welcome";

export const INFO_TEXT = "Insert text here";

function InfoButton({ labeled = false }: { labeled?: boolean }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const pointerFocused = useRef(false);
  return <div className="info-control" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
    <button className={labeled ? "mobile-nav-button" : "icon-button"} aria-label="About Rook" aria-describedby={open ? id : undefined}
      onPointerDown={() => { pointerFocused.current = true; }}
      onFocus={() => { if (!pointerFocused.current) setOpen(true); }}
      onBlur={() => { pointerFocused.current = false; setOpen(false); }}
      onClick={() => { setOpen(true); pointerFocused.current = false; }}
      onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setOpen(false); } }}>
      <Info size={20} strokeWidth={1.6} aria-hidden="true" />
      {labeled && <span>About Rook</span>}
    </button>
    {open && <div role="tooltip" id={id} className="info-tooltip">{INFO_TEXT}</div>}
  </div>;
}

function MobileAbout() {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <div className="mobile-about">
    <button className="mobile-nav-button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((current) => !current)}>
      <Info size={20} strokeWidth={1.6} aria-hidden="true" />
      <span>About Rook</span>
      <ChevronDown className="mobile-about-chevron" size={18} aria-hidden="true" />
    </button>
    {open && <div className="mobile-about-content" id={id}><p>{INFO_TEXT}</p></div>}
  </div>;
}

interface Props {
  messages: Message[];
  loading: boolean;
  error: string | null;
  composerVersion?: number;
  administrator?: boolean;
  onOpenSidebar: () => void;
  onNew: () => void;
  onSend: (message: string) => void;
}

export function ChatWindow({ messages, loading, error, composerVersion, administrator, onOpenSidebar, onNew, onSend }: Props) {
  const empty = messages.length === 0;
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  useEffect(() => {
    if (!mobileMenuOpen) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setMobileMenuOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileMenuOpen]);
  const startNewConversation = () => {
    setMobileMenuOpen(false);
    onNew();
  };
  const composer = <div className="composer-area">
    {error && <div role="alert" className="error-message">{error}</div>}
    <MessageInput key={composerVersion} disabled={loading} onSend={onSend} />
  </div>;
  return <main className="chat-window">
    <header className="chat-header">
      <button className="icon-button mobile-menu-trigger" onClick={() => setMobileMenuOpen(true)} aria-label="Open menu">
        <Menu size={21} aria-hidden="true" />
      </button>
      {administrator && <SidebarTrigger onClick={onOpenSidebar} />}
      <div className="header-actions">
        <button className="new-conversation" disabled={loading} onClick={startNewConversation}>
          <Plus size={17} aria-hidden="true" /><span>New conversation</span>
        </button>
        <InfoButton />
      </div>
    </header>
    {mobileMenuOpen && <button className="mobile-nav-overlay" aria-label="Close menu" onClick={() => setMobileMenuOpen(false)} />}
    <aside className={`mobile-nav-panel ${mobileMenuOpen ? "is-open" : ""}`} aria-label="Rook menu" aria-hidden={!mobileMenuOpen}>
      <div className="mobile-nav-heading">
        <RookLogo size="menu" />
        <button className="icon-button" onClick={() => setMobileMenuOpen(false)} aria-label="Close menu">
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <div className="mobile-nav-actions">
        <button className="mobile-nav-button" disabled={loading} onClick={startNewConversation}>
          <Plus size={18} aria-hidden="true" /><span>New conversation</span>
        </button>
        {administrator && <button className="mobile-nav-button" onClick={() => { setMobileMenuOpen(false); onOpenSidebar(); }}>
          <MessageSquare size={18} aria-hidden="true" /><span>Conversations</span>
        </button>}
      </div>
      <div className="mobile-nav-footer">
        <MobileAbout />
        <ThemeToggle labeled />
      </div>
    </aside>
    {empty ? <div className="welcome-area"><Welcome />{composer}</div> : <>
      <MessageList messages={messages} loading={loading} />
      <div className="active-composer">
        {composer}
      </div>
    </>}
  </main>;
}

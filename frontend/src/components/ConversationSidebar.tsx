import { Menu, MessageSquare, Plus, X } from "lucide-react";
import type { Conversation } from "../types";

interface Props {
  conversations: Conversation[];
  currentId: string | null;
  open: boolean;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
}

export function ConversationSidebar({ conversations, currentId, open, onClose, onNew, onSelect }: Props) {
  return (
    <>
      {open && <button aria-label="Close navigation" className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={onClose} />}
      <aside className={`fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-stone-200 bg-stone-100 transition-transform md:static md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-16 items-center justify-between px-4">
          <div className="flex items-center gap-3 font-semibold text-stone-900">
            <span className="grid size-9 place-items-center bg-emerald-700 text-lg font-bold text-white">R</span>
            Rook
          </div>
          <button className="icon-button md:hidden" onClick={onClose} aria-label="Close sidebar"><X size={19} /></button>
        </div>
        <div className="px-3 pb-3">
          <button className="flex h-10 w-full items-center justify-center gap-2 bg-stone-900 px-3 text-sm font-medium text-white hover:bg-stone-700" onClick={onNew}>
            <Plus size={17} /> New conversation
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 pb-4" aria-label="Conversations">
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              className={`mb-1 flex h-11 w-full items-center gap-3 px-3 text-left text-sm ${currentId === conversation.id ? "bg-white text-stone-950 shadow-sm" : "text-stone-600 hover:bg-stone-200/70"}`}
              onClick={() => { onSelect(conversation.id); onClose(); }}
            >
              <MessageSquare size={16} className="shrink-0" />
              <span className="truncate">{conversation.title}</span>
            </button>
          ))}
        </nav>
      </aside>
    </>
  );
}

export function SidebarTrigger({ onClick }: { onClick: () => void }) {
  return <button className="icon-button md:hidden" onClick={onClick} aria-label="Open sidebar"><Menu size={20} /></button>;
}

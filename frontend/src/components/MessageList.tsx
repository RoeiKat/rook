import { useLayoutEffect, useRef } from "react";
import type { Message } from "../types";

export function MessageList({ messages, loading }: { messages: Message[]; loading: boolean }) {
  const scroller = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  useLayoutEffect(() => {
    if (scroller.current && followLatest.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [messages, loading]);
  return <div ref={scroller} className="message-list" aria-label="Chat messages" onScroll={() => {
    const element = scroller.current;
    if (element) followLatest.current = element.scrollHeight - element.scrollTop - element.clientHeight < 64;
  }}>
    <div className="message-column">
      {messages.map((message) => <article key={message.id} className={`message message-${message.role}`}>
        <span className="sr-only">{message.role === "user" ? "You" : "Rook"}</span>
        <p>{message.content || (loading ? "Thinking..." : "")}</p>
      </article>)}
    </div>
  </div>;
}

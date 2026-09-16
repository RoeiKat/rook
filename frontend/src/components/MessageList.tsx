import { useLayoutEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { Message } from "../types";

const ROLE_LABELS: Record<Message["role"], string> = {
  user: "You",
  assistant: "Rook",
  system: "System prompt",
  tool: "Tool answer",
};

function MessageContent({ message, loading }: { message: Message; loading: boolean }) {
  if (message.role === "assistant") {
    if (!message.content && loading) {
      return <p className="thinking-indicator" role="status">Thinking...</p>;
    }
    return <div className="message-markdown"><ReactMarkdown>{message.content}</ReactMarkdown></div>;
  }
  if (message.role === "system" || message.role === "tool") {
    return <><strong className="message-role">{ROLE_LABELS[message.role]}</strong><p>{message.content}</p></>;
  }
  return <p>{message.content}</p>;
}

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
        <span className="sr-only">{ROLE_LABELS[message.role]}</span>
        <MessageContent message={message} loading={loading} />
      </article>)}
    </div>
  </div>;
}

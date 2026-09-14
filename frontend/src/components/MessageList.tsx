import { useLayoutEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { Message } from "../types";

function MessageContent({ message, loading }: { message: Message; loading: boolean }) {
  const content = message.content || (loading ? "Thinking..." : "");
  if (message.role === "assistant") {
    return <div className="message-markdown"><ReactMarkdown>{content}</ReactMarkdown></div>;
  }
  return <p>{content}</p>;
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
        <span className="sr-only">{message.role === "user" ? "You" : "Rook"}</span>
        <MessageContent message={message} loading={loading} />
      </article>)}
    </div>
  </div>;
}

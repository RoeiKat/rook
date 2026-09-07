import { useEffect, useRef } from "react";
import type { Message } from "../types";

export function MessageList({ messages, loading }: { messages: Message[]; loading: boolean }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), [messages, loading]);

  if (!messages.length) {
    return (
      <div className="grid flex-1 place-items-center px-6">
        <div className="max-w-md text-center">
          <div className="mx-auto mb-5 grid size-12 place-items-center bg-emerald-700 text-xl font-bold text-white">R</div>
          <h1 className="text-2xl font-semibold text-stone-900">What can I help with?</h1>
          <p className="mt-2 text-sm leading-6 text-stone-500">Ask a question about your documents or start a conversation.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-8">
      <div className="mx-auto max-w-3xl space-y-7">
        {messages.map((message) => (
          <article key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={message.role === "user" ? "max-w-[85%] rounded-lg bg-stone-200 px-4 py-3 text-stone-900" : "w-full text-stone-800"}>
              <p className="whitespace-pre-wrap text-[15px] leading-7">{message.content || (loading ? "Thinking..." : "")}</p>
            </div>
          </article>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

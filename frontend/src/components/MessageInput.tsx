import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";

export function MessageInput({ disabled, onSend }: { disabled: boolean; onSend: (value: string) => void }) {
  const [value, setValue] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    if (!textarea.current) return;
    textarea.current.style.height = "0px";
    textarea.current.style.height = `${Math.max(28, Math.min(textarea.current.scrollHeight, 160))}px`;
  }, [value]);
  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const message = value.trim();
    if (!message || disabled) return;
    setValue("");
    onSend(message);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };
  return <form onSubmit={submit} className="message-composer">
    <textarea ref={textarea} aria-label="Message" rows={1} value={value}
      onChange={(event) => setValue(event.target.value)} onKeyDown={onKeyDown}
      placeholder="Message Rook" />
    <button className="send-button" disabled={disabled || !value.trim()} aria-label="Send message">
      <ArrowUp size={20} strokeWidth={2} aria-hidden="true" />
    </button>
  </form>;
}

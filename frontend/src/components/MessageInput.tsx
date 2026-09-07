import { FormEvent, KeyboardEvent, useState } from "react";
import { ArrowUp } from "lucide-react";

export function MessageInput({ disabled, onSend }: { disabled: boolean; onSend: (value: string) => void }) {
  const [value, setValue] = useState("");
  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const message = value.trim();
    if (!message || disabled) return;
    setValue("");
    onSend(message);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };
  return (
    <form onSubmit={submit} className="mx-auto flex max-w-3xl items-end gap-2 border border-stone-300 bg-white p-2 shadow-sm focus-within:border-stone-500">
      <textarea
        aria-label="Message"
        rows={1}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Message Rook"
        className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[15px] leading-6 outline-none placeholder:text-stone-400"
      />
      <button className="grid size-10 shrink-0 place-items-center bg-emerald-700 text-white disabled:bg-stone-300" disabled={disabled || !value.trim()} aria-label="Send message">
        <ArrowUp size={19} />
      </button>
    </form>
  );
}

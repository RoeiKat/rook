// @vitest-environment jsdom

import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Message } from "../src/types";
import { MessageList } from "../src/components/MessageList";

const message: Message = {
  id: "message-1",
  role: "user",
  content: "Hello",
  created_at: "2026-09-07T00:00:00Z",
};

describe("MessageList", () => {
  it("renders assistant Markdown while keeping user messages plain", () => {
    const { container } = render(<MessageList messages={[
      { ...message, content: "**Literal user text**" },
      { ...message, id: "reply", role: "assistant", content: "**Important answer**" },
    ]} loading={false} />);

    const [userMessage, assistantMessage] = container.querySelectorAll("article");
    expect(userMessage.querySelector("strong")).toBeNull();
    expect(userMessage.textContent).toContain("**Literal user text**");
    expect(assistantMessage.querySelector("strong")?.textContent).toBe("Important answer");
  });

  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn(() => ({}) as never);
  });

  it("does not treat the scroll result as an effect cleanup function", () => {
    const view = render(<MessageList messages={[message]} loading={false} />);

    expect(() => {
      view.rerender(<MessageList messages={[message]} loading />);
      view.unmount();
    }).not.toThrow();
  });

  it("labels and renders administrator system and tool records", () => {
    const { getByText } = render(<MessageList messages={[
      { ...message, id: "system", role: "system", content: "System instructions" },
      { ...message, id: "tool", role: "tool", content: "Retrieved context" },
    ]} loading={false} />);

    expect(getByText("System prompt", { selector: ".message-role" })).toBeTruthy();
    expect(getByText("System instructions")).toBeTruthy();
    expect(getByText("Tool answer", { selector: ".message-role" })).toBeTruthy();
    expect(getByText("Retrieved context")).toBeTruthy();
  });

  it("shows the animated thinking state with an ellipsis while awaiting a response", () => {
    const { getByRole } = render(<MessageList messages={[
      { ...message, id: "reply", role: "assistant", content: "" },
    ]} loading />);

    const indicator = getByRole("status");
    expect(indicator.textContent).toBe("Thinking...");
    expect(indicator.classList.contains("thinking-indicator")).toBe(true);
  });

  it("keeps the reading position during streaming and resumes following at the bottom", () => {
    const view = render(<MessageList messages={[message]} loading />);
    const scroller = view.container.querySelector(".message-list") as HTMLElement;
    Object.defineProperties(scroller, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { value: 300 } });
    scroller.scrollTop = 150;
    fireEvent.scroll(scroller);
    view.rerender(<MessageList messages={[message, { ...message, id: "reply", role: "assistant", content: "More text" }]} loading />);
    expect(scroller.scrollTop).toBe(150);
    scroller.scrollTop = 700;
    fireEvent.scroll(scroller);
    Object.defineProperty(scroller, "scrollHeight", { value: 1200 });
    view.rerender(<MessageList messages={[message, { ...message, id: "reply", role: "assistant", content: "More text continued" }]} loading />);
    expect(scroller.scrollTop).toBe(1200);
  });
});

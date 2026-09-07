// @vitest-environment jsdom

import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Message } from "../types";
import { MessageList } from "./MessageList";

const message: Message = {
  id: "message-1",
  role: "user",
  content: "Hello",
  created_at: "2026-09-07T00:00:00Z",
};

describe("MessageList", () => {
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
});

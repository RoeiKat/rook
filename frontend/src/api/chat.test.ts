import { describe, expect, it, vi } from "vitest";
import { streamChat } from "./chat";

describe("streamChat", () => {
  it("parses events split across transport chunks", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream({ start(controller) {
      controller.enqueue(encoder.encode('event: metadata\ndata: {"conversation_id":"abc"}\n\nevent: tok'));
      controller.enqueue(encoder.encode('en\ndata: "Hello"\n\n'));
      controller.close();
    }});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const onMetadata = vi.fn();
    const onToken = vi.fn();
    await streamChat("Hi", null, { onMetadata, onToken });
    expect(onMetadata).toHaveBeenCalledWith("abc");
    expect(onToken).toHaveBeenCalledWith("Hello");
  });
});

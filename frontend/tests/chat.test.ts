import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createConversation, getConversation, getSession, listConversations, login, logout, streamChat } from "../src/api/chat";

afterEach(() => vi.unstubAllGlobals());

describe("streamChat", () => {
  it("parses events split across transport chunks", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream({ start(controller) {
      controller.enqueue(encoder.encode('event: metadata\ndata: {"conversation_id":"abc","title":"Roei projects"}\n\nevent: tok'));
      controller.enqueue(encoder.encode('en\ndata: "Hello"\n\nevent: done\ndata: {"message_id":"answer"}\n\n'));
      controller.close();
    }});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const onMetadata = vi.fn();
    const onToken = vi.fn();
    const onDone = vi.fn();
    await streamChat("Hi", null, { onMetadata, onToken, onDone });
    expect(onMetadata).toHaveBeenCalledWith("abc", "Roei projects");
    expect(onToken).toHaveBeenCalledWith("Hello");
    expect(onDone).toHaveBeenCalledWith("answer");
    const options = vi.mocked(fetch).mock.calls[0][1]!;
    expect(options.credentials).toBe("include");
    expect(new Headers(options.headers).get("X-CSRF-Protection")).toBe("1");
    expect(JSON.parse(options.body as string)).toEqual({ message: "Hi", conversation_id: null });
  });

  it("handles CRLF delimiters split between chunks", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream({ start(controller) {
      for (const part of ['event: token\r\ndata: "Hello"\r', '\n\r', '\nevent: done\r\ndata: {"message_id":"answer"}\r\n\r\n']) {
        controller.enqueue(encoder.encode(part));
      }
      controller.close();
    }});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    const onToken = vi.fn();
    await streamChat("Hi", "abc", { onMetadata: vi.fn(), onToken });
    expect(onToken).toHaveBeenCalledExactlyOnceWith("Hello");
  });

  it("rejects an incomplete stream instead of reporting success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('event: token\ndata: "Partial"\n\n')));
    await expect(streamChat("Hi", null, { onMetadata: vi.fn(), onToken: vi.fn() })).rejects.toThrow("ended before it finished");
  });

  it("surfaces sanitized stream errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('event: error\ndata: {"message":"Unable to generate a response"}\n\n')));
    await expect(streamChat("Hi", null, { onMetadata: vi.fn(), onToken: vi.fn() })).rejects.toThrow("Unable to generate a response");
  });
});

describe("cookie-authenticated API requests", () => {
  it("includes credentials on all requests and CSRF protection on mutations", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response("{}")));
    await getSession();
    await login("admin", "test-password");
    await logout();
    await listConversations();
    await getConversation("conversation-id");
    await createConversation("What has Roei built?");
    for (const [, options] of vi.mocked(fetch).mock.calls) {
      expect(options?.credentials).toBe("include");
      if (options?.method === "POST") expect(new Headers(options.headers).get("X-CSRF-Protection")).toBe("1");
    }
    expect(JSON.parse(vi.mocked(fetch).mock.calls[5][1]?.body as string)).toEqual({ message: "What has Roei built?" });
  });

  it("preserves HTTP status for access handling", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"Not found"}', { status: 404 })));
    await expect(getConversation("inaccessible")).rejects.toMatchObject({ status: 404, message: "Not found" });
    expect(new ApiError("Unauthorized", 401)).toBeInstanceOf(Error);
  });
});

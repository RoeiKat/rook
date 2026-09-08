// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import indexHtml from "../../index.html?raw";
import { ChatWindow, INFO_TEXT } from "./ChatWindow";
import { RookLogo } from "./RookLogo";
import { ThemeToggle } from "./ThemeToggle";
import { Welcome, WELCOME } from "./Welcome";
import { MessageInput } from "./MessageInput";

function mediaPreferences({ dark = false, reduced = false } = {}) {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query.includes("reduced-motion") ? reduced : dark,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.dataset.theme = "light";
  mediaPreferences();
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("appearance", () => {
  it("uses the supplied SVG at both sizes and falls back to text if unavailable", () => {
    render(<><RookLogo /><RookLogo size="welcome" /></>);
    const logos = screen.getAllByRole("img", { name: "Rook" });
    expect(logos).toHaveLength(2);
    expect(logos.every((image) => image.getAttribute("src") === "/rook.svg")).toBe(true);
    fireEvent.error(logos[0]);
    expect(screen.getByText("Rook")).toBeTruthy();
  });

  it.each([
    [null, true, "dark"], [null, false, "light"], ["light", true, "light"], ["dark", false, "dark"],
  ])("sets the theme before paint (saved %s, system dark %s)", (saved, dark, expected) => {
    mediaPreferences({ dark });
    if (saved) localStorage.setItem("rook.theme", saved);
    const script = indexHtml.match(/<script>([\s\S]*?)<\/script>/)![1];
    new Function(script)();
    expect(document.documentElement.dataset.theme).toBe(expected);
    expect(document.documentElement.style.colorScheme).toBe(expected);
  });

  it("switches and persists the selected theme", () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Switch to dark mode" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("rook.theme")).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "Switch to light mode" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("rook.theme")).toBe("light");
  });

  it("shows the exact tooltip with hover, keyboard focus and touch, and dismisses on Escape", () => {
    render(<ChatWindow title="Rook" messages={[]} loading={false} error={null} onOpenSidebar={vi.fn()} onNew={vi.fn()} onSend={vi.fn()} />);
    const info = screen.getByRole("button", { name: "About Rook" });
    fireEvent.mouseEnter(info.parentElement!);
    expect(screen.getByRole("tooltip").textContent).toBe(INFO_TEXT);
    fireEvent.mouseLeave(info.parentElement!);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(info);
    expect(info.getAttribute("aria-describedby")).toBe(screen.getByRole("tooltip").id);
    fireEvent.keyDown(info, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.blur(info);
    fireEvent.pointerDown(info, { pointerType: "touch" });
    fireEvent.click(info);
    expect(screen.getByRole("tooltip")).toBeTruthy();
  });
});

describe("welcome animation", () => {
  it("types, pauses and deletes in the specified order with a stable accessible heading", () => {
    vi.useFakeTimers();
    const view = render(<Welcome />);
    const typed = () => view.container.querySelector(".welcome-typed")!.textContent;
    expect(typed()).toBe("");
    act(() => vi.advanceTimersByTime(WELCOME.betweenMs));
    expect(typed()).toBe("W");
    for (let index = 1; index < WELCOME.sentences[0].length; index++) act(() => vi.advanceTimersByTime(WELCOME.typeMs));
    expect(typed()).toBe(WELCOME.sentences[0]);
    expect(screen.getByRole("heading").textContent).toContain(WELCOME.sentences[0]);
    act(() => vi.advanceTimersByTime(WELCOME.pauseMs));
    for (let index = 0; index <= WELCOME.sentences[0].length; index++) act(() => vi.advanceTimersByTime(WELCOME.deleteMs));
    expect(typed()).toBe("");
    act(() => vi.advanceTimersByTime(WELCOME.betweenMs));
    expect(typed()).toBe("L");
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("shows a complete static heading without timers or cursor for reduced motion", () => {
    mediaPreferences({ reduced: true });
    vi.useFakeTimers();
    const view = render(<Welcome />);
    expect(view.container.querySelector(".welcome-typed")!.textContent).toBe(WELCOME.sentences[0]);
    expect(view.container.querySelector(".typing-cursor")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });
});

it("keeps Enter/Shift+Enter behavior and prevents blank or duplicate submissions", () => {
  const send = vi.fn();
  const view = render(<MessageInput disabled={false} onSend={send} />);
  const input = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(input, { target: { value: "Hello" } });
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  expect(send).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(send).toHaveBeenCalledWith("Hello");
  fireEvent.change(input, { target: { value: "  " } });
  fireEvent.keyDown(input, { key: "Enter" });
  view.rerender(<MessageInput disabled onSend={send} />);
  fireEvent.change(input, { target: { value: "Another" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(send).toHaveBeenCalledTimes(1);
});

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

export function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  useEffect(() => {
    const preference = window.matchMedia?.("(prefers-color-scheme: dark)");
    const followSystem = () => {
      let saved: string | null = null;
      try { saved = localStorage.getItem("rook.theme"); } catch { /* Storage can be disabled. */ }
      if (saved === "light" || saved === "dark") return;
      const next = preference?.matches ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      document.documentElement.style.colorScheme = next;
      setTheme(next);
    };
    preference?.addEventListener("change", followSystem);
    return () => preference?.removeEventListener("change", followSystem);
  }, []);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
    setTheme(next);
    try { localStorage.setItem("rook.theme", next); } catch { /* Theme still works without storage. */ }
  };
  return <button className="icon-button theme-toggle" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} onClick={toggle}>
    {theme === "dark" ? <Sun size={20} aria-hidden="true" /> : <Moon size={20} aria-hidden="true" />}
  </button>;
}

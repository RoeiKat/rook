import { AdminPage } from "./components/AdminPage";
import { ConversationChat } from "./components/ConversationChat";
import { RookLogo } from "./components/RookLogo";
import { ThemeToggle } from "./components/ThemeToggle";

export function getAdminPath(value = import.meta.env.VITE_ADMIN_PATH): string {
  const path = value?.trim() || "/admin";
  if (!/^\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/.test(path)) {
    throw new Error("VITE_ADMIN_PATH must be an absolute path containing only letters, numbers, dashes, and underscores");
  }
  return path;
}

export default function App() {
  const adminPath = getAdminPath();
  const currentPath = window.location.pathname.replace(/\/+$/, "") || "/";
  const isAdminPage = currentPath === adminPath || currentPath === `${adminPath}/login`;

  return (
    <div className="app-shell">
      <aside className="brand-rail" aria-label="Rook appearance">
        <RookLogo />
        <ThemeToggle />
      </aside>
      <div className="app-content">
        {isAdminPage ? <AdminPage /> : <ConversationChat />}
      </div>
    </div>
  );
}

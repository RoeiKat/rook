import { AdminPage } from "./components/AdminPage";
import { ConversationChat } from "./components/ConversationChat";
import { RookLogo } from "./components/RookLogo";
import { ThemeToggle } from "./components/ThemeToggle";

export default function App() {
  const isAdminPage = /^\/admin(?:\/login)?\/?$/.test(window.location.pathname);

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

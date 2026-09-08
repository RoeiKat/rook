import { useCallback, useEffect, useState } from "react";
import { AdminAccess, AdminPage } from "./components/AdminPage";
import { ConversationChat } from "./components/ConversationChat";
import { RookLogo } from "./components/RookLogo";
import { ThemeToggle } from "./components/ThemeToggle";

export default function App() {
  const [path, setPath] = useState(window.location.pathname);
  const navigate = useCallback((destination: string) => {
    window.history.replaceState({}, "", destination);
    setPath(destination);
  }, []);
  const goHome = useCallback(() => navigate("/"), [navigate]);
  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPopState);
    // Registration remains disabled, including direct visits to common aliases.
    if (/^\/(?:admin\/)?(?:register|registration)\/?$/.test(path)) goHome();
    return () => window.removeEventListener("popstate", onPopState);
  }, [path, goHome]);
  const content = /^\/admin\/access\/?$/.test(path)
    ? <AdminAccess onGranted={() => navigate("/admin")} onDenied={goHome} />
    : /^\/(?:admin(?:\/login)?|login)\/?$/.test(path)
      ? <AdminPage onAccessDenied={goHome} /> : <ConversationChat />;
  return <div className="app-shell">
    <aside className="brand-rail" aria-label="Rook appearance">
      <RookLogo />
      <ThemeToggle />
    </aside>
    <div className="app-content">{content}</div>
  </div>;
}

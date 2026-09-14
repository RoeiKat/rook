import { useEffect, useState, type FormEvent } from "react";
import { getSession, login, logout } from "../api/chat";
import { ConversationChat } from "./ConversationChat";
import { KnowledgeBase } from "./KnowledgeBase";

type SessionState = "checking" | "anonymous" | "admin";

export function AdminPage() {
  const [session, setSession] = useState<SessionState>("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<"conversations" | "knowledge">("conversations");

  useEffect(() => {
    const controller = new AbortController();
    getSession(controller.signal)
      .then(({ is_admin }) => setSession(is_admin ? "admin" : "anonymous"))
      .catch(() => setError("Could not check the administrator session."));
    return () => controller.abort();
  }, []);

  const signIn = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await login(username, password);
      setPassword("");
      if (!result.is_admin) throw new Error("Unable to establish an administrator session.");
      setSession("admin");
    } catch (failure) {
      setPassword("");
      setError(failure instanceof Error ? failure.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    setSession("anonymous");
    try {
      await logout();
    } catch {
      setError("The server could not confirm sign out. Please try again.");
    }
  };

  if (session === "checking") {
    return <main className="session-loading"><p role="status">Checking session...</p></main>;
  }

  if (session === "admin") {
    return (
      <div className="admin-shell">
        <header className="admin-navigation">
          <nav aria-label="Administrator sections">
            <button aria-current={section === "conversations" ? "page" : undefined} onClick={() => setSection("conversations")}>Conversations</button>
            <button aria-current={section === "knowledge" ? "page" : undefined} onClick={() => setSection("knowledge")}>Knowledge base</button>
          </nav>
          <button onClick={signOut} className="sign-out admin-sign-out">Sign out</button>
        </header>
        <div className="admin-section">
          {section === "conversations"
            ? <ConversationChat administrator onAuthenticationFailure={() => {
                setError("Your administrator session has ended. Please sign in again.");
                setSession("anonymous");
              }} />
            : <KnowledgeBase onAuthenticationFailure={() => {
                setError("Your administrator session has ended. Please sign in again.");
                setSession("anonymous");
              }} />}
        </div>
      </div>
    );
  }

  return (
    <main className="auth-page">
      <form onSubmit={signIn} className="auth-form">
        <h1 className="auth-heading">Rook administrator</h1>
        <label className="auth-label">
          Username
          <input
            name="username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
            disabled={busy}
            className="auth-input"
          />
        </label>
        <label className="auth-label">
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            disabled={busy}
            className="auth-input"
          />
        </label>
        {error && <p role="alert" className="auth-error">{error}</p>}
        <button disabled={busy} className="auth-submit">
          {busy ? "Please wait..." : "Sign in"}
        </button>
        <a href="/" className="auth-home">Return to chat</a>
      </form>
    </main>
  );
}

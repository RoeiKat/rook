import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, checkAdminAccess, getSession, login, logout, unlockAdminAccess } from "../api/chat";
import { ConversationChat } from "./ConversationChat";

export function AdminPage({ onAccessDenied }: { onAccessDenied: () => void }) {
  const [session, setSession] = useState<"checking" | "anonymous" | "admin">("checking");
  const [checkingSession, setCheckingSession] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logoutFailed, setLogoutFailed] = useState(false);
  const requestVersion = useRef(0);
  const loginRequest = useRef<AbortController | null>(null);
  const pendingMutation = useRef(false);

  const clearSession = useCallback(() => {
    requestVersion.current += 1;
    loginRequest.current?.abort();
    setSession("checking");
    setCheckingSession(false);
    setUsername("");
    setPassword("");
    setError("Your administrator session has ended. Please sign in again.");
    const version = requestVersion.current;
    void checkAdminAccess().then(() => {
      if (version === requestVersion.current) setSession("anonymous");
    }).catch(() => {
      if (version === requestVersion.current) onAccessDenied();
    });
  }, [onAccessDenied]);

  useEffect(() => {
    const controller = new AbortController();
    checkAdminAccess(controller.signal).then(() => getSession(controller.signal)).then((result) => {
      if (!controller.signal.aborted) setSession(result.is_admin === true ? "admin" : "anonymous");
    }).catch(() => {
      if (!controller.signal.aborted) {
        onAccessDenied();
      }
    });
    return () => {
      controller.abort();
      loginRequest.current?.abort();
      requestVersion.current += 1;
    };
  }, [onAccessDenied]);

  // Revalidate history when returning to a tab, including after sign-out elsewhere.
  useEffect(() => {
    if (session === "checking") return;
    const controller = new AbortController();
    let pending = false;
    const validate = () => {
      if (pending) return;
      const version = requestVersion.current;
      pending = true;
      setCheckingSession(true);
      void checkAdminAccess(controller.signal).then(() => getSession(controller.signal)).then((result) => {
        if (!controller.signal.aborted && version === requestVersion.current && session === "admin" && result.is_admin !== true) clearSession();
      }).catch(() => {
        if (!controller.signal.aborted && version === requestVersion.current) onAccessDenied();
      }).finally(() => {
        pending = false;
        if (!controller.signal.aborted && version === requestVersion.current) setCheckingSession(false);
      });
    };
    window.addEventListener("focus", validate);
    return () => { controller.abort(); window.removeEventListener("focus", validate); };
  }, [session, clearSession, onAccessDenied]);

  const signIn = async (event: FormEvent) => {
    event.preventDefault();
    if (pendingMutation.current) return;
    pendingMutation.current = true;
    setBusy(true);
    setError(null);
    const version = ++requestVersion.current;
    const controller = new AbortController();
    loginRequest.current = controller;
    const submittedPassword = password;
    setPassword("");
    try {
      await login(username, submittedPassword, controller.signal);
      const result = await getSession(controller.signal);
      if (controller.signal.aborted || version !== requestVersion.current) return;
      if (result.is_admin !== true) throw new Error("Unable to establish an administrator session. Please try again.");
      setUsername("");
      setSession("admin");
    } catch (failure) {
      if (!controller.signal.aborted && version === requestVersion.current) {
        if (failure instanceof ApiError && failure.status === 403) { onAccessDenied(); return; }
        setError(failure instanceof Error ? failure.message : "Unable to sign in. Please try again.");
      }
    } finally {
      pendingMutation.current = false;
      if (!controller.signal.aborted && version === requestVersion.current) setBusy(false);
    }
  };

  const signOut = async () => {
    if (pendingMutation.current) return;
    clearSession();
    setError(null);
    setLogoutFailed(false);
    pendingMutation.current = true;
    setBusy(true);
    const version = requestVersion.current;
    try {
      await logout();
      if (version === requestVersion.current) onAccessDenied();
    } catch {
      if (version === requestVersion.current) {
        setLogoutFailed(true);
        setError("Sign-out could not be confirmed. Please try signing out again.");
      }
    } finally {
      pendingMutation.current = false;
      if (version === requestVersion.current) setBusy(false);
    }
  };

  if (session === "checking" || (checkingSession && session === "anonymous")) return <main className="session-loading"><p role="status">Checking session...</p></main>;
  if (session === "admin") return <ConversationChat administrator checkingSession={checkingSession} onAuthenticationFailure={clearSession} onLogout={signOut} />;

  return (
    <main className="auth-page">
      <form onSubmit={signIn} className="auth-form">
        <h1 className="auth-heading">Rook administrator</h1>
        <label className="auth-label">Username
          <input name="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required disabled={busy} className="auth-input" />
        </label>
        <label className="auth-label">Password
          <input name="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required disabled={busy} className="auth-input" />
        </label>
        {error && <p role="alert" className="auth-error">{error}</p>}
        {logoutFailed && <button type="button" disabled={busy} onClick={signOut} className="auth-retry">Retry sign out</button>}
        <button disabled={busy} className="auth-submit">{busy ? "Please wait..." : "Sign in"}</button>
        <a href="/" className="auth-home">Return to chat</a>
      </form>
    </main>
  );
}

export function AdminAccess({ onGranted, onDenied }: { onGranted: () => void; onDenied: () => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const unlock = async (event: FormEvent) => {
    event.preventDefault();
    if (request.current) return;
    if (!password) { onDenied(); return; }
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    const submittedPassword = password;
    setPassword("");
    try {
      await unlockAdminAccess(submittedPassword, controller.signal);
      if (!controller.signal.aborted) onGranted();
    } catch {
      if (!controller.signal.aborted) onDenied();
    }
  };
  return (
    <main className="auth-page">
      <form onSubmit={unlock} className="auth-form">
        <h1 className="auth-heading">Administrator access</h1>
        <label className="auth-label">Access password
          <input type="password" autoComplete="off" value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} className="auth-input" />
        </label>
        <button disabled={busy} className="auth-submit">{busy ? "Checking..." : "Continue"}</button>
        <a href="/" className="auth-home">Return to chat</a>
      </form>
    </main>
  );
}

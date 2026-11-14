import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api, clearToken, getToken, saveToken, SESSION_EXPIRED_EVENT } from "./api.js";
import { useFeedback } from "./feedback.jsx";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const { notify } = useFeedback();

  useEffect(() => {
    let alive = true;
    const bootstrapToken = getToken();
    if (!bootstrapToken) {
      setReady(true);
      return () => { alive = false; };
    }
    api("/auth/me")
      .then((profile) => { if (alive && getToken() === bootstrapToken) setUser(profile); })
      .catch((err) => {
        if (!alive || getToken() !== bootstrapToken) return;
        if (err?.status === 401 || err?.code === "account_inactive") {
          clearToken();
          if (err?.code === "account_inactive") {
            notify("warning", "This account is inactive. Contact your administrator for access.");
          }
        } else if (err?.status === 0 || err?.status >= 500 || !err?.status) {
          notify("error", "QueMe could not verify your saved session because its authentication service is unavailable. Your session was kept; please try again when the service is available.");
        }
        setUser(null);
      })
      .finally(() => { if (alive) setReady(true); });
    return () => { alive = false; };
  }, [notify]);

  useEffect(() => {
    function handleSessionExpired() {
      clearToken();
      setUser(null);
      notify("warning", "Your session expired. Please sign in again.");
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, [notify]);

  const value = useMemo(() => ({
    user,
    ready,
    async login(email, password) {
      const result = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      saveToken(result.token);
      setUser(result.user);
      return result.user;
    },
    async register(payload) {
      return api("/auth/register", { method: "POST", body: JSON.stringify(payload) });
    },
    logout() {
      clearToken();
      setUser(null);
    },
  }), [user, ready]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider.");
  return value;
}

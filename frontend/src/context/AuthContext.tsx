import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Platform } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import { api, getStoredToken, setStoredToken, User } from "@/src/api/client";

type AuthState = {
  user: User | null;
  loading: boolean;
  loginWithGoogle: () => Promise<void>;
  loginAsAdmin: (email: string, password: string) => Promise<void>;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

const EMERGENT_AUTH_URL = "https://auth.emergentagent.com/";

function parseSessionId(url: string | null | undefined): string | null {
  if (!url) return null;
  // Support both ?session_id=... and #session_id=...
  const hashIdx = url.indexOf("#");
  if (hashIdx >= 0) {
    const hashStr = url.substring(hashIdx + 1);
    const params = new URLSearchParams(hashStr);
    const sid = params.get("session_id");
    if (sid) return sid;
  }
  const qIdx = url.indexOf("?");
  if (qIdx >= 0) {
    const qStr = url.substring(qIdx + 1).split("#")[0];
    const params = new URLSearchParams(qStr);
    const sid = params.get("session_id");
    if (sid) return sid;
  }
  return null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const token = await getStoredToken();
      if (!token) {
        setUser(null);
        return;
      }
      const me = await api.me();
      setUser(me);
    } catch {
      await setStoredToken(null);
      setUser(null);
    }
  }, []);

  useEffect(() => {
    (async () => {
      // Web cold start: parse session_id off URL
      if (Platform.OS === "web" && typeof window !== "undefined") {
        const sid = parseSessionId(window.location.href);
        if (sid) {
          try {
            const res = await api.googleSession(sid);
            await setStoredToken(res.session_token);
            setUser(res.user);
            window.history.replaceState(null, "", window.location.pathname);
            setLoading(false);
            return;
          } catch (e) {
            console.warn("Web session exchange failed", e);
          }
        }
      } else {
        // Mobile cold start fallback
        try {
          const initial = await Linking.getInitialURL();
          const sid = parseSessionId(initial);
          if (sid) {
            const res = await api.googleSession(sid);
            await setStoredToken(res.session_token);
            setUser(res.user);
            setLoading(false);
            return;
          }
        } catch {}
      }
      await refresh();
      setLoading(false);
    })();
  }, [refresh]);

  const loginWithGoogle = useCallback(async () => {
    const redirectUrl =
      Platform.OS === "web" && typeof window !== "undefined"
        ? window.location.origin + "/"
        : Linking.createURL("auth");

    const authUrl = `${EMERGENT_AUTH_URL}?redirect=${encodeURIComponent(redirectUrl)}`;

    if (Platform.OS === "web" && typeof window !== "undefined") {
      window.location.href = authUrl;
      return;
    }

    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
    if (result.type !== "success" || !result.url) {
      throw new Error("Login cancelled");
    }
    const sid = parseSessionId(result.url);
    if (!sid) throw new Error("Missing session id");
    const res = await api.googleSession(sid);
    await setStoredToken(res.session_token);
    setUser(res.user);
  }, []);

  const loginAsAdmin = useCallback(async (email: string, password: string) => {
    const res = await api.adminLogin(email, password);
    await setStoredToken(res.session_token);
    setUser(res.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {}
    await setStoredToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, loginWithGoogle, loginAsAdmin, refresh, logout }),
    [user, loading, loginWithGoogle, loginAsAdmin, refresh, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

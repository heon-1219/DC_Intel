import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";

import { api, getToken, setToken, setUnauthorizedHandler } from "../api/client";
import type { AuthUser, Lang } from "../api/types";

interface AuthCtx {
  token: string | null;
  user: AuthUser | null;
  isAuthed: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, language: Lang) => Promise<void>;
  logout: () => void;
}
const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<AuthUser | null>(null);

  // Any API 401 → clear session and redirect to login preserving where we were (§2.2).
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setTokenState(null);
      setUser(null);
      const here = window.location.pathname + window.location.search;
      if (!here.startsWith("/login")) {
        navigate(`/login?returnTo=${encodeURIComponent(here)}`, { replace: true });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await api.login(email, password);
    setToken(data.access_token);
    setTokenState(data.access_token);
    setUser(data.user);
  }, []);

  const register = useCallback(async (email: string, password: string, language: Lang) => {
    const { data } = await api.register(email, password, language);
    setToken(data.access_token);
    setTokenState(data.access_token);
    setUser(data.user);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setTokenState(null);
    setUser(null);
    navigate("/login", { replace: true });
  }, [navigate]);

  const value = useMemo<AuthCtx>(
    () => ({ token, user, isAuthed: !!token, login, register, logout }),
    [token, user, login, register, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

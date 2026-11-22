import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/endpoints";
import { getToken, setToken, setUnauthorizedHandler } from "../api/client";
import type { AppMode, Config, User } from "../api/types";

interface AuthState {
  config: Config | null;
  configError: string;
  user: User | null;
  loading: boolean;
  signIn: (user: User, token: string) => void;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
  loginRequired: boolean;
  mode: AppMode;
  reloadConfig: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [configError, setConfigError] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const signIn = useCallback((u: User, token: string) => {
    setToken(token);
    setUser(u);
  }, []);

  const signOut = useCallback(async () => {
    try {
      if (getToken()) await api.logout();
    } catch {
      // sessão já expirou no servidor
    }
    setToken("");
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    setUser(await api.me());
  }, []);

  // Depois da troca de modo: a configuração muda e a sessão do outro modo deixa de valer.
  const reloadConfig = useCallback(async () => {
    setConfig(await api.config());
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    (async () => {
      try {
        const cfg = await api.config();
        setConfig(cfg);
        if (cfg.login_enabled && getToken()) {
          try {
            setUser(await api.me());
          } catch {
            setUser(null);
          }
        }
      } catch (e) {
        setConfigError(e instanceof Error ? e.message : "API indisponível");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      config,
      configError,
      user,
      loading,
      signIn,
      signOut,
      refreshUser,
      loginRequired: config?.login_enabled ?? true,
      mode: config?.mode ?? "solo",
      reloadConfig,
    }),
    [config, configError, user, loading, signIn, signOut, refreshUser, reloadConfig],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth fora do AuthProvider");
  return ctx;
}

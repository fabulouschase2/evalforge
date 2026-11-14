import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthState {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, name: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(() => {
    const raw = localStorage.getItem("evalforge_user");
    return raw ? (JSON.parse(raw) as User) : null;
  });
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("evalforge_token"));
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Re-validate stored token on mount
    if (token) {
      api.get<User>("/auth/me")
        .then((u) => {
          setUser(u);
          localStorage.setItem("evalforge_user", JSON.stringify(u));
        })
        .catch(() => {
          setUser(null);
          setToken(null);
          localStorage.removeItem("evalforge_token");
          localStorage.removeItem("evalforge_user");
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const persist = useCallback((data: { access_token: string; user: User }) => {
    localStorage.setItem("evalforge_token", data.access_token);
    localStorage.setItem("evalforge_user", JSON.stringify(data.user));
    setToken(data.access_token);
    setUser(data.user);
    return data.user;
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      const data = await api.post<{ access_token: string; user: User }>("/auth/login", { email, password });
      return persist(data);
    } finally {
      setLoading(false);
    }
  }, [persist]);

  const register = useCallback(async (email: string, name: string, password: string) => {
    setLoading(true);
    try {
      const data = await api.post<{ access_token: string; user: User }>("/auth/register", { email, name, password });
      return persist(data);
    } finally {
      setLoading(false);
    }
  }, [persist]);

  const logout = useCallback(() => {
    localStorage.removeItem("evalforge_token");
    localStorage.removeItem("evalforge_user");
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, token, loading, login, register, logout }),
    [user, token, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

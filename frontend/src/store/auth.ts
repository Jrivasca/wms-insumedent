import { createContext, createElement, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import * as authApi from '../api/auth';
import { TOKEN_KEY, USER_KEY } from '../api/http';
import type { User } from '../types';

interface AuthState {
  token: string | null;
  currentUser: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

function readStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [currentUser, setCurrentUser] = useState<User | null>(() => readStoredUser());
  const [loading, setLoading] = useState<boolean>(false);

  // If we have a token but no cached user, fetch it.
  useEffect(() => {
    if (token && !currentUser) {
      setLoading(true);
      authApi
        .me()
        .then((u) => {
          setCurrentUser(u);
          localStorage.setItem(USER_KEY, JSON.stringify(u));
        })
        .catch(() => {
          // interceptor handles 401 cleanup
        })
        .finally(() => setLoading(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(email: string, password: string): Promise<User> {
    setLoading(true);
    try {
      const res = await authApi.login(email, password);
      localStorage.setItem(TOKEN_KEY, res.access_token);
      localStorage.setItem(USER_KEY, JSON.stringify(res.user));
      setToken(res.access_token);
      setCurrentUser(res.user);
      return res.user;
    } finally {
      setLoading(false);
    }
  }

  async function logout(): Promise<void> {
    await authApi.logout();
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setCurrentUser(null);
  }

  async function refresh(): Promise<void> {
    const u = await authApi.me();
    setCurrentUser(u);
    localStorage.setItem(USER_KEY, JSON.stringify(u));
  }

  const value: AuthState = { token, currentUser, loading, login, logout, refresh };
  return createElement(AuthContext.Provider, { value }, children);
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

/** Role helpers shared across the app. */
export function isOperario(role?: string): boolean {
  return role === 'picker' || role === 'packer' || role === 'operario';
}

export function isSupervisor(role?: string): boolean {
  return role === 'admin' || role === 'supervisor';
}

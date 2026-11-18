import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { loadSession, signIn, signOut, subscribeSession, type SessionUser } from './sessionClient';
import { loadBranding } from '../system/branding';

export type AuthState = {
  user: SessionUser | null;
  status: 'loading' | 'ready' | 'error';
  error: string;
  signIn: typeof signIn;
  signOut: typeof signOut;
  refresh: () => Promise<void>;
};
const AuthContext = createContext<AuthState | null>(null);

export type AuthProviderProps = { children: ReactNode };

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [status, setStatus] = useState<AuthState['status']>('loading');
  const [error, setError] = useState('');
  async function refresh() {
    setStatus('loading');
    try { await loadSession(); setError(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '세션 확인 실패'); setStatus('error'); }
  }
  useEffect(() => {
    const unsubscribe = subscribeSession(session => {
      setUser(session?.user ?? null);
      setStatus('ready');
      setError('');
    });
    void loadBranding();  // system name, logo, favicon and theme apply to the sign-in page too
    void refresh();
    return unsubscribe;
  }, []);
  return <AuthContext.Provider value={{ user, status, error, signIn, signOut, refresh }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('useAuth requires AuthProvider');
  return auth;
}

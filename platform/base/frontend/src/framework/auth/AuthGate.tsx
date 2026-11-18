import type { ReactNode } from 'react';
import { Button } from '../ui';
import { useAuth } from './AuthProvider';
import { LoginForm } from './LoginForm';
import { useBranding } from '../system/useBranding';

export type AuthGateProps = { children: ReactNode };

export function AuthGate({ children }: AuthGateProps) {
  const auth = useAuth();
  const branding = useBranding();
  if (auth.status === 'loading') return <div role="status">로그인 상태 확인 중…</div>;
  if (auth.status === 'error') return <div role="alert">{auth.error}<Button label="다시 확인" onClick={() => void auth.refresh()} /></div>;
  if (!auth.user) return <main data-ui="login-page" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center',
    ...(branding.loginBackground ? { backgroundImage: `url("${branding.loginBackground}")`, backgroundSize: 'cover', backgroundPosition: 'center' } : {}) }}><LoginForm onSignIn={auth.signIn} /></main>;
  return children;
}

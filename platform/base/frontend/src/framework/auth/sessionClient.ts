/** What a role may do inside one program (screen). */
export type ProgramPermission = { query: boolean; create: boolean; save: boolean; delete: boolean; print: boolean };
/** A menu node: a FOLDER holds children, a PROGRAM opens the screen with that program code. */
export type MenuEntry = { id?: number | null; type?: 'FOLDER' | 'PROGRAM'; programCode: string | null; name: string; order: number; icon?: string | null; children?: MenuEntry[] };
export type MenuModule = { code: string; name: string; icon?: string | null; menus: MenuEntry[] };
export type MenuSystem = { code: string; name: string; modules: MenuModule[] };
/**
 * roles/admin: role-based access. menus: system > module > menu the roles may open.
 * programs: permissions per program code (administrators may do everything). unassigned: programs
 * not placed in a menu yet (administrators only). All optional for older servers.
 */
export type SessionUser = { username: string; displayName: string; permissions: string[]; roles?: string[]; admin?: boolean;
  menus?: MenuSystem[]; programs?: Record<string, ProgramPermission>; unassigned?: MenuEntry[] };
export type SessionInfo = { authenticated: boolean; user: SessionUser | null; csrf: { headerName: string; token: string } };
type Listener = (session: SessionInfo | undefined) => void;
let current: SessionInfo | undefined;
let generation = 0;
const listeners = new Set<Listener>();

function publish(session: SessionInfo | undefined) {
  current = session;
  listeners.forEach(listener => listener(session));
}

export function subscribeSession(listener: Listener) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

// Why the last session ended, shown once on the login page (e.g. the account signed in somewhere else).
let notice = '';
export function sessionNotice() { return notice; }
export function clearSessionNotice() { notice = ''; }
async function replaced(response: Response): Promise<boolean> {
  if (response.status !== 401) return false;
  const code = await response.clone().json().then(body => (body as { error?: string }).error, () => undefined);
  if (code !== 'SESSION_REPLACED') return false;
  notice = '같은 계정이 다른 곳에서 로그인하여 이 접속이 종료되었습니다.';
  return true;
}

export async function loadSession(): Promise<SessionInfo> {
  const requestedGeneration = generation;
  let response = await fetch('/api/auth/session', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
  // A replaced session answers once with the reason; asking again gives the signed-out session.
  if (await replaced(response)) response = await fetch('/api/auth/session', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error('로그인 상태를 확인하지 못했습니다.');
  const session: SessionInfo = await response.json();
  if (typeof session.authenticated !== 'boolean' || !session.csrf?.token || !session.csrf.headerName || (session.authenticated && !session.user))
    throw new Error('서버의 세션 응답을 확인할 수 없습니다.');
  if (generation === requestedGeneration) publish(session);
  return session;
}

export async function signIn(username: string, password: string): Promise<void> {
  const session = await loadSession();
  const response = await fetch('/api/auth/login', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', [session.csrf.headerName]: session.csrf.token },
    body: new URLSearchParams({ username, password }),
  });
  if (!response.ok) {
    const code = await response.json().then(body => (body as { error?: string }).error, () => undefined);
    throw new Error(code === 'ACCOUNT_NOT_ACTIVE' ? '아직 사용할 수 없는 계정입니다. 관리자 승인을 기다리거나 관리자에게 문의하세요.'
      : response.status === 401 ? '아이디 또는 비밀번호가 올바르지 않습니다.' : '로그인하지 못했습니다. 다시 시도하세요.');
  }
  generation++;
  notice = '';
  const authenticated = await loadSession();
  if (!authenticated.authenticated) throw new Error('로그인 세션을 확인하지 못했습니다.');
}

export async function signOut(): Promise<void> {
  const session = current ?? await loadSession();
  const response = await fetch('/api/auth/logout', {
    method: 'POST', credentials: 'same-origin', headers: { [session.csrf.headerName]: session.csrf.token },
  });
  if (!response.ok && response.status !== 401) throw new Error('로그아웃하지 못했습니다. 다시 시도하세요.');
  generation++;
  publish(undefined);
  await loadSession();
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const rawUrl = input instanceof Request ? input.url : String(input);
  const url = new URL(rawUrl, window.location.href);
  if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/')) return fetch(input, init);
  const method = (init.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init.headers).forEach((value, name) => headers.set(name, value));
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const session = current ?? await loadSession();
    headers.set(session.csrf.headerName, session.csrf.token);
  }
  const requestedGeneration = generation;
  const response = await fetch(input, { ...init, headers, credentials: 'same-origin' });
  if (response.status === 401) await replaced(response);
  if (response.status === 401 && generation === requestedGeneration) {
    generation++;
    publish(undefined);
    void loadSession().catch(() => {});
  }
  return response;
}

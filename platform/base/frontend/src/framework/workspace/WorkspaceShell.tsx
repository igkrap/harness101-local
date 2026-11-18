import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { HStack, Text, VStack, tabPanelId, tabTitleId } from '../ui';
import { AsyncFeedback } from '../AsyncFeedback';
import type { SessionUser } from '../auth/sessionClient';
import { accessibleScreens, canonicalWorkspace, menuGroups, type ScreenRegistry } from './registry';
import { apiFetch, loadSession } from '../auth/sessionClient';
import { useBranding } from '../system/useBranding';
import { ProgramCodeContext, ProgramPermissionContext, permissionFor } from '../system/programAccess';
import { closeTab, openTab, sanitizeWorkspace, type WorkspaceState, closeTabs, moveTab } from './state';
import { DirtyContext } from './DirtyContext';
import { ScreenBoundary } from './ScreenBoundary';
import { WorkspaceSidebar } from './WorkspaceSidebar';
import { WorkspaceTabs } from './WorkspaceTabs';
import { AccountDialog } from '../system/AccountDialog';
import { WorkspaceNavContext } from './navContext';

export type WorkspaceShellProps = {
  screens: ScreenRegistry;
  initialWorkspace: WorkspaceState;
  user: SessionUser;
  onLogout: () => Promise<void>;
  title?: string;
};

function ScreenPanel({ id, children, update }: { id: string; children: ReactNode; update: (id: string, key: string, dirty: boolean) => void }) {
  const setDirty = useCallback((key: string, dirty: boolean) => update(id, key, dirty), [id, update]);
  return <DirtyContext.Provider value={setDirty}><ScreenBoundary>{children}</ScreenBoundary></DirtyContext.Provider>;
}

export function WorkspaceShell({ screens, initialWorkspace, user, onLogout, title }: WorkspaceShellProps) {
  const branding = useBranding();
  const systemName = title ?? branding.systemName;
  const available = useMemo(() => accessibleScreens(screens, user), [screens, user]);
  const groups = useMemo(() => menuGroups(available, user), [available, user]);
  // Screens register themselves as programs: an administrator's session reports them, new ones wait as 미편성 프로그램.
  const programKey = Object.values(screens).filter(screen => screen.meta.code).map(screen => `${screen.id}:${screen.meta.title}:${(screen.apis ?? []).join(',')}`).sort().join('|');
  useEffect(() => {
    if (!user.admin || !programKey) return;
    const programs = Object.values(screens).filter(screen => screen.meta.code).map(screen => ({ code: screen.id, name: screen.meta.title,
      apiPaths: screen.apis ?? [], systemProgram: screen.meta.system ?? screen.id.startsWith('SYS') }));
    void apiFetch('/api/system/programs/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ programs }) })
      .then(async response => { if (response.ok && (await response.json()).added > 0) await loadSession(); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.admin, user.username, programKey]);
  // Favourites are the user's own list (kept on the server), shown at the top of the sidebar.
  const [favorites, setFavorites] = useState<string[]>([]);
  useEffect(() => {
    void apiFetch('/api/auth/favorites').then(async response => { if (response.ok) setFavorites(await response.json() as string[]); }).catch(() => {});
  }, [user.username]);
  function setFavorite(id: string, on: boolean) {
    setFavorites(previous => on ? [...previous.filter(item => item !== id), id] : previous.filter(item => item !== id));  // shown at once; the server answer confirms
    void apiFetch(`/api/auth/favorites/${encodeURIComponent(id)}`, { method: on ? 'PUT' : 'DELETE' })
      .then(async response => { if (response.ok) setFavorites(await response.json() as string[]); else setError('즐겨찾기를 저장하지 못했습니다.'); })
      .catch(() => setError('즐겨찾기를 저장하지 못했습니다.'));
  }
  const [accountOpen, setAccountOpen] = useState(false);
  const [intents, setIntents] = useState<Record<string, { at: number; values: Record<string, string> }>>({});
  // Access log: each program is reported when it is opened (once per open tab).
  const reported = useRef(new Set<string>());
  useEffect(() => {
    const id = state.activeTab;
    for (const known of [...reported.current]) if (!state.tabs.includes(known)) reported.current.delete(known);
    if (!id || reported.current.has(id) || !available[id]?.meta.code) return;
    reported.current.add(id);
    void apiFetch('/api/auth/usage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ programCode: id }) }).catch(() => {});
  });
  const allowed = Object.keys(available).sort().join('\n');
  const initialKey = JSON.stringify(initialWorkspace);
  const previousInitial = useRef(initialKey);
  const [state, setState] = useState(() => sanitizeWorkspace(canonicalWorkspace(initialWorkspace, available), Object.keys(available)));
  const [dirtyKeys, setDirtyKeys] = useState<Record<string, string[]>>({});
  const [error, setError] = useState('');
  const dirty = new Set(Object.keys(dirtyKeys).filter(id => dirtyKeys[id].length > 0));
  useEffect(() => {
    const changed = previousInitial.current !== initialKey;
    previousInitial.current = initialKey;
    setState(current => sanitizeWorkspace(canonicalWorkspace(changed ? JSON.parse(initialKey) as WorkspaceState : current, available), allowed.split('\n')));
  }, [initialKey, allowed]);
  const updateDirty = useCallback((id: string, key: string, value: boolean) => {
    setDirtyKeys(previous => {
      const keys = previous[id] ?? [];
      if (keys.includes(key) === value) return previous;
      return { ...previous, [id]: value ? [...keys, key] : keys.filter(item => item !== key) };
    });
  }, []);
  // Deep link: #open=<program code or screen title> opens that screen whatever module it sits in.
  useEffect(() => {
    const open = () => {
      const wanted = decodeURIComponent((window.location.hash.match(/[#&]open=([^&]+)/)?.[1] ?? '')).trim();
      if (!wanted) return;
      const screen = available[wanted] ?? Object.values(available).find(item => item.meta.title === wanted);
      if (screen) setState(current => openTab(current, screen.id));
    };
    open();
    window.addEventListener('hashchange', open);
    return () => window.removeEventListener('hashchange', open);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed]);
  // Sign-ups waiting for approval show as a badge on 사용자 관리 (administrators).
  const [badges, setBadges] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!user.admin) return;
    let active = true;
    const load = () => void apiFetch('/api/system/users').then(async response => response.ok ? response.json() as Promise<{ status: string }[]> : [])
      .then(list => { if (active) setBadges({ SYS0001: list.filter(item => item.status === 'PENDING').length }); }).catch(() => {});
    load();
    const timer = window.setInterval(load, 60000);
    return () => { active = false; window.clearInterval(timer); };
  }, [user.admin, user.username]);
  const hasDirty = dirty.size > 0;
  useEffect(() => {
    if (!hasDirty) return;
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [hasDirty]);
  function requestClose(id: string) {
    if (dirty.has(id) && !window.confirm('저장하지 않은 변경이 있습니다. 화면을 닫을까요?')) return;
    setState(current => closeTab(current, id));
  }
  function requestCloseMany(ids: string[]) {
    const unsaved = ids.filter(id => dirty.has(id)).length;
    if (unsaved && !window.confirm(`저장하지 않은 변경이 있는 화면이 ${unsaved}개 있습니다. 닫을까요?`)) return;
    setState(current => closeTabs(current, ids));
  }
  async function requestLogout() {
    if (hasDirty && !window.confirm('저장하지 않은 변경이 있습니다. 로그아웃할까요?')) return;
    try { await onLogout(); } catch (cause) { setError(cause instanceof Error ? cause.message : '로그아웃 실패'); }
  }
  const nav = { groups, intents, open: (id: string, intent?: Record<string, string>) => {
    if (intent) setIntents(previous => ({ ...previous, [id]: { at: Date.now(), values: intent } }));
    setState(current => openTab(current, id));
  }, favorites, badges, userName: user.displayName, systemName, logo: branding.logo };
  return <WorkspaceNavContext.Provider value={nav}><HStack style={{ height: '100vh', minHeight: 0 }}>
    <WorkspaceSidebar groups={groups} logo={branding.logo} collapsed={state.sidebarCollapsed} onCollapsedChange={sidebarCollapsed => setState(current => ({ ...current, sidebarCollapsed }))}
      active={state.activeTab} onOpen={id => setState(current => openTab(current, id))} title={systemName} userLabel={user.displayName} userName={user.username} badges={badges} favorites={favorites} onFavorite={setFavorite} onAccount={() => setAccountOpen(true)} onLogout={() => void requestLogout()} />
    <VStack gap={0} style={{ flex: 1, height: '100%', minWidth: 0, minHeight: 0, overflow: 'hidden' }}>
      <WorkspaceTabs screens={available} tabs={state.tabs} active={state.activeTab} dirty={dirty} onSelect={activeTab => setState(current => ({ ...current, activeTab }))} onClose={requestClose} onCloseMany={requestCloseMany} onMove={(id, target) => setState(current => moveTab(current, id, target))} favorites={favorites} onFavorite={setFavorite} />
      <AsyncFeedback error={error} />
      <AccountDialog isOpen={accountOpen} onClose={() => setAccountOpen(false)} />
      <main style={{ display: 'flex', flex: 1, width: '100%', minHeight: 0, padding: 12, overflow: 'auto', boxSizing: 'border-box' }}>
        {state.tabs.length === 0 && <Text>활성화된 탭이 없습니다.</Text>}
        {state.tabs.map(id => {
          const screen = available[id];
          if (!screen) return null;
          const Screen = screen.Component;
          return <section key={id} id={tabPanelId('workspace', id)} role="tabpanel" aria-labelledby={tabTitleId('workspace', id)} hidden={state.activeTab !== id}
            style={{ display: state.activeTab === id ? 'flex' : 'none', flexDirection: 'column', flex: 1, minWidth: 0, minHeight: 0 }}>
            <ProgramPermissionContext.Provider value={permissionFor(user, id, Boolean(screen.meta.code))}>
              <ProgramCodeContext.Provider value={screen.meta.code ? id : ''}><ScreenPanel id={id} update={updateDirty}><Screen /></ScreenPanel></ProgramCodeContext.Provider>
            </ProgramPermissionContext.Provider>
          </section>;
        })}
      </main>
    </VStack>
  </HStack></WorkspaceNavContext.Provider>;
}

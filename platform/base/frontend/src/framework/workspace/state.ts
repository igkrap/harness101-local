export type WorkspaceState = { tabs: string[]; activeTab: string; sidebarCollapsed: boolean };

export function sanitizeWorkspace(state: WorkspaceState, allowed: readonly string[]): WorkspaceState {
  const tabs = [...new Set(state.tabs)].filter(id => allowed.includes(id));
  return { ...state, tabs, activeTab: tabs.includes(state.activeTab) ? state.activeTab : tabs[0] ?? '' };
}

export function openTab(state: WorkspaceState, id: string): WorkspaceState {
  return { ...state, tabs: state.tabs.includes(id) ? state.tabs : [...state.tabs, id], activeTab: id };
}

export function closeTab(state: WorkspaceState, id: string): WorkspaceState {
  const index = state.tabs.indexOf(id);
  const tabs = state.tabs.filter(tab => tab !== id);
  return { ...state, tabs, activeTab: state.activeTab === id ? tabs[Math.min(index, tabs.length - 1)] ?? '' : state.activeTab };
}

/** Close several tabs at once; the active tab moves to the nearest one that stays open. */
export function closeTabs(state: WorkspaceState, ids: readonly string[]): WorkspaceState {
  const tabs = state.tabs.filter(tab => !ids.includes(tab));
  if (tabs.includes(state.activeTab)) return { ...state, tabs };
  const index = state.tabs.indexOf(state.activeTab);
  const after = state.tabs.slice(index + 1).find(tab => tabs.includes(tab));
  const before = state.tabs.slice(0, Math.max(index, 0)).reverse().find(tab => tabs.includes(tab));
  return { ...state, tabs, activeTab: after ?? before ?? '' };
}

/** Move tab `id` to where tab `target` is. */
export function moveTab(state: WorkspaceState, id: string, target: string): WorkspaceState {
  if (id === target || !state.tabs.includes(id) || !state.tabs.includes(target)) return state;
  const index = state.tabs.indexOf(target);
  const tabs = state.tabs.filter(tab => tab !== id);
  tabs.splice(index, 0, id);
  return { ...state, tabs };
}

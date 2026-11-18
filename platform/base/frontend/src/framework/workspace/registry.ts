import type { ComponentType } from 'react';
import type { MenuEntry, SessionUser } from '../auth/sessionClient';
import { parseScreenCode } from './screenCode';
import type { WorkspaceState } from './state';

/** keywords: words users would type to find the screen (synonyms, related terms); the sidebar search indexes them. */
/** system: a system administration program (default: codes starting with SYS) - false for built-in work screens such as 수불 마감. */
export type ScreenMeta = { code?: string; title: string; group?: string; order?: number; permissions?: string[]; hidden?: boolean; icon?: string; keywords?: string[]; system?: boolean;
  /** The API paths the screen's program owns (permissions), when they are not found in its source. */ apis?: string[] };
export type ScreenModule = { meta: ScreenMeta; default: ComponentType };
export type ScreenDefinition = { id: string; legacyId?: string; meta: ScreenMeta; Component: ComponentType; /** API prefixes found in the screen source (for program permissions). */ apis?: string[] };
export type ScreenRegistry = Record<string, ScreenDefinition>;

/** sources: the same files as raw text (import.meta.glob(..., { query: '?raw', import: 'default', eager: true })), to find each screen's APIs. */
// The framework's own administration screens (사용자·역할·메뉴·권한·설정) are part of every app.
const systemScreens = import.meta.glob('../system/screens/*.tsx', { eager: true }) as Record<string, ScreenModule>;

export function createScreenRegistry(appModules: Record<string, ScreenModule>, sources: Record<string, string> = {}): ScreenRegistry {
  const modules = { ...systemScreens, ...appModules };
  const seen = new Set<string>();
  return Object.fromEntries(Object.entries(modules).map(([path, module]) => {
    const legacyId = path.split('/').pop()?.replace(/\.tsx$/, '') ?? path;
    const id = module.meta?.code ? parseScreenCode(module.meta.code).code : legacyId;
    if (!module.meta?.title || !module.default) throw new Error(`Screen ${id} requires meta.title and a default component`);
    if (seen.has(id)) throw new Error(`Duplicate screen code: ${id}`);
    seen.add(id);
    const apis = [...new Set((sources[path] ?? '').match(/\/api\/[a-z][a-z0-9-]*/g) ?? [])].filter(api => !api.startsWith('/api/auth') && !api.startsWith('/api/system'));
    return [id, { id, legacyId, meta: module.meta, Component: module.default, apis: module.meta.apis ?? apis }];
  }));
}

export function canonicalWorkspace(state: WorkspaceState, screens: ScreenRegistry): WorkspaceState {
  const resolve = (id: string) => screens[id] ? id : Object.values(screens).find(screen => screen.legacyId === id)?.id ?? id;
  return { ...state, tabs: state.tabs.map(resolve), activeTab: resolve(state.activeTab) };
}

/**
 * Screens the user may open. With role data from the server: administrators see everything; others see the
 * programs in their menus plus screens without a program code (홈). Older servers fall back to meta.permissions.
 */
export function accessibleScreens(screens: ScreenRegistry, user: SessionUser): ScreenRegistry {
  const legacy = ([, screen]: [string, ScreenDefinition]) => (screen.meta.permissions ?? []).every(permission => user.permissions.includes(permission));
  if (!user.menus) return Object.fromEntries(Object.entries(screens).filter(legacy));
  if (user.admin) return screens;
  const granted = new Set(user.menus.flatMap(system => system.modules.flatMap(module => programCodes(module.menus))));
  return Object.fromEntries(Object.entries(screens).filter(([id, screen]) => !screen.meta.code || granted.has(id)));
}

function programCodes(menus: MenuEntry[]): string[] {
  return menus.flatMap(menu => menu.type === 'FOLDER' ? programCodes(menu.children ?? []) : menu.programCode ? [menu.programCode] : []);
}

/** One sidebar entry: a folder with children, or a screen. */
/** icon: set by the administrator for this menu (a built-in name or an SVG data: URL); otherwise folders use the folder icon and programs their screen's icon. */
export type MenuNode = { key: string; title: string; icon?: string; screen?: ScreenDefinition; children?: MenuNode[] };
/** A module with its 메뉴 tree. key '__home' holds screens without a program code, '__unassigned' the unplaced ones. */
export type MenuGroup = { key: string; title: string; icon?: string; nodes: MenuNode[] };

/**
 * Sidebar structure. With role data: one group per module the user may see (folders and programs in the
 * configured order), 홈 separately, and for administrators the screens not placed in any menu.
 * Older servers: groups by meta.group.
 */
export function menuGroups(screens: ScreenRegistry, user: SessionUser): MenuGroup[] {
  const visible = Object.values(screens).filter(screen => !screen.meta.hidden);
  const leaf = (screen: ScreenDefinition): MenuNode => ({ key: screen.id, title: screen.meta.title, screen });
  if (!user.menus) {
    const groups = new Map<string, ScreenDefinition[]>();
    [...visible].sort((a, b) => (a.meta.order ?? 0) - (b.meta.order ?? 0)).forEach(screen => {
      const group = screen.meta.group ?? '메뉴';
      groups.set(group, [...(groups.get(group) ?? []), screen]);
    });
    return [...groups].map(([title, items]) => ({ key: title, title, nodes: items.map(leaf) }));
  }
  const placed = new Set<string>();
  const build = (menus: MenuEntry[]): MenuNode[] => menus.flatMap((menu): MenuNode[] => {
    if (menu.type === 'FOLDER') {
      const children = build(menu.children ?? []);
      return children.length ? [{ key: `folder-${menu.id}`, title: menu.name, icon: menu.icon ?? undefined, children }] : [];
    }
    const screen = menu.programCode ? screens[menu.programCode] : undefined;
    if (!screen || screen.meta.hidden) return [];
    placed.add(screen.id);
    return [{ key: screen.id, title: menu.name || screen.meta.title, icon: menu.icon ?? undefined, screen }];
  });
  const result: MenuGroup[] = [];
  const home = visible.filter(screen => !screen.meta.code);
  home.forEach(screen => placed.add(screen.id));
  if (home.length) result.push({ key: '__home', title: '홈', icon: 'home', nodes: home.map(leaf) });
  for (const system of user.menus) for (const module of system.modules) {
    const nodes = build(module.menus);
    if (nodes.length) result.push({ key: module.code, title: module.name, icon: module.icon ?? undefined, nodes });
  }
  const rest = visible.filter(screen => !placed.has(screen.id));
  if (rest.length) result.push({ key: '__unassigned', title: '미편성 프로그램', icon: 'list', nodes: rest.map(leaf) });
  return result;
}

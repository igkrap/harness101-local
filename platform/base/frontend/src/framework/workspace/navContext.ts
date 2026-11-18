import { createContext, useContext } from 'react';
import type { MenuGroup } from './registry';

/** What a screen may know about the workspace around it (used by the home page). */
export type WorkspaceNav = {
  /** The menu the user may use (홈, modules, unplaced programs). */ groups: MenuGroup[];
  /** Open a screen in a tab; `intent` is handed to that screen (e.g. which record to show). */ open: (id: string, intent?: Record<string, string>) => void;
  /** The latest intent per screen id; `at` changes on every open so a screen can react again. */ intents: Record<string, { at: number; values: Record<string, string> }>;
  favorites: readonly string[];
  /** Counts by program code, e.g. sign-ups waiting for approval. */ badges: Record<string, number>;
  userName: string; systemName: string; logo: string;
};
export const WorkspaceNavContext = createContext<WorkspaceNav | null>(null);
export function useWorkspaceNav() { return useContext(WorkspaceNavContext); }

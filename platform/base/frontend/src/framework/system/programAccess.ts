import { createContext, useContext } from 'react';
import type { ProgramPermission, SessionUser } from '../auth/sessionClient';

export const ALL_ACTIONS: ProgramPermission = { query: true, create: true, save: true, delete: true, print: true };
export const NO_ACTIONS: ProgramPermission = { query: false, create: false, save: false, delete: false, print: false };

/** Permissions of the signed-in user in the screen being rendered (set by the workspace shell). */
export const ProgramPermissionContext = createContext<ProgramPermission>(ALL_ACTIONS);
export function useProgramPermission(): ProgramPermission { return useContext(ProgramPermissionContext); }
/** The program code of the screen being rendered ('' outside a screen): what a person's own settings of that screen are kept under. */
export const ProgramCodeContext = createContext('');
export function useProgramCode(): string { return useContext(ProgramCodeContext); }

/** Administrators and servers without role data may do everything; otherwise what the roles grant for that program. */
export function permissionFor(user: SessionUser, programCode: string, hasCode: boolean): ProgramPermission {
  if (user.admin || !user.programs || !hasCode) return ALL_ACTIONS;
  return user.programs[programCode] ?? NO_ACTIONS;
}

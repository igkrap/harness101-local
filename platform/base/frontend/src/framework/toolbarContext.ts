import { createContext, useContext } from 'react';

/** True inside a screen whose shared header toolbar (조회/신규/삭제/저장) drives its forms. */
export const SharedToolbarContext = createContext(false);

/** Forms show their own buttons only when no shared toolbar controls them, unless a screen says otherwise. */
export function useOwnActions(showActions: boolean | undefined) {
  const shared = useContext(SharedToolbarContext);
  return showActions ?? !shared;
}

/** True inside a region that gives the grid a fixed area (BusinessWorkspace results): the grid docks and fills it. */
export const GridDockContext = createContext(false);
export function useGridDock(): boolean {
  return useContext(GridDockContext);
}

import { createContext, useContext, useEffect, useId } from 'react';

export const DirtyContext = createContext<((key: string, dirty: boolean) => void) | null>(null);

export function useUnsavedChanges(dirty: boolean) {
  const update = useContext(DirtyContext);
  const key = useId();
  useEffect(() => {
    update?.(key, dirty);
    return () => update?.(key, false);
  }, [update, key, dirty]);
}

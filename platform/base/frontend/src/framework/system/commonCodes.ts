import { useEffect, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';

/** One common code: the stored value and the name shown to people. */
export type CommonCode = { code: string; name: string };
const cache = new Map<string, CommonCode[]>();
const waiting = new Map<string, Promise<CommonCode[]>>();

async function load(group: string): Promise<CommonCode[]> {
  const cached = cache.get(group);
  if (cached) return cached;
  let request = waiting.get(group);
  if (!request) {
    request = apiFetch(`/api/auth/codes?groups=${encodeURIComponent(group)}`).then(async response => {
      const list = response.ok ? ((await response.json()) as Record<string, CommonCode[]>)[group] ?? [] : [];
      if (response.ok) cache.set(group, list);
      waiting.delete(group);
      return list;
    }, () => { waiting.delete(group); return []; });
    waiting.set(group, request);
  }
  return request;
}

/** Forget cached codes (after an administrator edits them). */
export function refreshCommonCodes(group?: string) { if (group) cache.delete(group); else cache.clear(); }

/**
 * The codes of a common-code group (공통 코드 관리), for drop-downs and for showing names in grids:
 *   const units = useCommonCodes('UNIT');  units.codes -> [{code,name}], units.name('EA') -> '개'
 */
export function useCommonCodes(group: string) {
  const [codes, setCodes] = useState<CommonCode[]>(cache.get(group) ?? []);
  useEffect(() => { let alive = true; void load(group).then(list => { if (alive) setCodes(list); }); return () => { alive = false; }; }, [group]);
  return { codes, name: (code: unknown) => codes.find(item => item.code === String(code ?? ''))?.name ?? String(code ?? ''),
    options: [{ value: '', label: '선택' }, ...codes.map(item => ({ value: item.code, label: item.name }))] };
}

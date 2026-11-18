import { useEffect, useState } from 'react';
import { apiFetch } from './auth/sessionClient';

/** A field whose value is a record of another screen (e.g. an employee's department): where to read the choices. */
export type Lookup = {
  /** List API of the other record, e.g. '/api/departments'. */ api: string;
  /** Which of its fields to show, e.g. 'name'. */ label: string;
  /** Which of its fields is stored (default 'id'). */ value?: string;
  /** How it is chosen (default 'dropdown') and, for the search window, which columns it lists. */
  pick?: 'dropdown' | 'search' | 'popup'; columns?: { key: string; label: string; align?: 'right' | 'center'; text?: (value: unknown) => string }[]; title?: string;
  /** Which of its fields is its code, shown before the name everywhere ('V-001 한빛상사'). */ code?: string;
};
type Choice = { value: string; label: string; code?: string; row?: Record<string, unknown> };
type Rows = Record<string, unknown>[];
const cache = new Map<string, { choices: Choice[]; more: boolean }>();
const keyOf = (lookup: Lookup) => `${lookup.api}|${lookup.label}|${lookup.value ?? 'id'}|${lookup.code ?? ''}`;

/** Forget loaded choices (after the other record changed). */
export function refreshLookup(api?: string) { for (const key of [...cache.keys()]) if (!api || key.startsWith(api + '|')) cache.delete(key); }

/**
 * Records of another screen, as much as is needed: the first ones (no arguments), those matching what was typed (q), or
 * exactly those with these ids. `more` says the screen holds only a part - there are more than came back - so it must
 * search on the server instead of in what it holds.
 */
export async function fetchLookup(api: string, ask: { q?: string; ids?: readonly string[] } = {}): Promise<{ rows: Rows; more: boolean }> {
  const parameters = new URLSearchParams();
  if (ask.q?.trim()) parameters.set('q', ask.q.trim());
  if (ask.ids?.length) parameters.set('ids', ask.ids.join(','));
  if (ask.q?.trim()) parameters.set('_limit', '200');
  const response = await apiFetch(parameters.size ? `${api}?${parameters}` : api);
  if (!response.ok) return { rows: [], more: false };
  const rows = await response.json() as Rows, total = Number(response.headers.get('X-Total-Count') ?? rows.length);
  return { rows: Array.isArray(rows) ? rows : [], more: total > rows.length };
}
/** Rows merged into what a screen already holds of an entity (by id, the newer row wins). */
export function mergeRows(held: Rows | undefined, found: Rows): Rows {
  if (!found.length) return held ?? [];
  const ids = new Set(found.map(row => String(row.id)));
  return [...(held ?? []).filter(row => !ids.has(String(row.id))), ...found];
}

/**
 * Choices of a lookup, for a drop-down and for showing the name in a grid:
 *   const dept = useLookup({ api: '/api/departments', label: 'name' });
 *   dept.options -> [{value,label}] (with an empty '선택'),  dept.name(row.departmentId) -> '개발팀'
 * The list is read again each time the screen is opened, so new records appear. When the other screen has more records
 * than one reading brings (dept.more), dept.search(typed) asks the server and dept.ensure(value) brings one record by its id.
 */
export function useLookup(lookup: Lookup) {
  const key = keyOf(lookup);
  const [state, setState] = useState<{ choices: Choice[]; more: boolean }>(cache.get(key) ?? { choices: [], more: false });
  const choice = (row: Record<string, unknown>): Choice => ({ value: String(row[lookup.value ?? 'id'] ?? ''), label: String(row[lookup.label] ?? ''), code: lookup.code ? String(row[lookup.code] ?? '') : undefined, row });
  const merge = (found: Choice[]) => setState(previous => {
    const values = new Set(found.map(item => item.value));
    const next = { choices: [...previous.choices.filter(item => !values.has(item.value)), ...found], more: previous.more };
    cache.set(key, next);
    return next;
  });
  useEffect(() => {
    let alive = true;
    void fetchLookup(lookup.api).then(({ rows, more }) => {
      const next = { choices: rows.map(choice).filter(item => item.value), more };
      cache.set(key, next);
      if (alive) setState(next);
    }).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const { choices, more } = state;
  return { choices, more, options: [{ value: '', label: '선택' }, ...choices],
    search: async (typed: string) => { const found = (await fetchLookup(lookup.api, { q: typed })).rows.map(choice).filter(item => item.value); merge(found); return found; },
    ensure: async (value: string) => { if (!value || choices.some(item => item.value === value)) return; merge((await fetchLookup(lookup.api, { ids: [value] })).rows.map(choice)); },
    name: (value: unknown) => { const found = choices.find(item => item.value === String(value ?? ''));
      return found ? [found.code, found.label].filter(Boolean).join(' ') : (value === null || value === undefined ? '' : String(value)); } };
}

/** The lines of a master with details to choose from (a step of an item's routing): those of the records whose `field` is `value`. */
export async function fetchLines(entity: string, field?: string | null, value?: string, ids?: readonly string[]): Promise<Record<string, unknown>[]> {
  const parameters = new URLSearchParams();
  if (field && value) { parameters.set('field', field); parameters.set('value', value); }
  if (ids?.length) parameters.set('ids', ids.join(','));
  const response = await apiFetch(`/api/lookup/${entity}/lines?${parameters.toString()}`);
  return response.ok ? await response.json() as Record<string, unknown>[] : [];
}

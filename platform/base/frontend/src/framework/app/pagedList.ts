import { useRef, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';

export type ListSort = { key: string; descending: boolean } | null;
/** Rows a screen brings at a time. The server holds the rest; the count line under the list says how many there are. */
export const PAGE = 500;

/**
 * A list that may be longer than what the screen holds: the first part, more on request, put in order by the server,
 * and the whole of it when a file is made. `failure` turns a refused request into the error to show.
 */
export function usePagedList<Row extends { id: string }>(api: string, toRow: (data: Record<string, unknown>) => Row,
  failure: (response: Response) => Promise<Error>, initialSort: ListSort = null) {
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState<number | undefined>(undefined);
  const asked = useRef<{ parameters: Record<string, string>; sort: ListSort }>({ parameters: {}, sort: initialSort });
  async function bring(offset: number, limit: number): Promise<{ rows: Row[]; total: number }> {
    const { parameters, sort } = asked.current;
    const query = new URLSearchParams({ ...parameters, _limit: String(limit), _offset: String(offset) });
    if (sort) { query.set('_sort', sort.key); if (sort.descending) query.set('_desc', 'true'); }
    const response = await apiFetch(`${api}?${query}`);
    if (!response.ok) throw await failure(response);
    const list = (await response.json() as Record<string, unknown>[]).map(toRow);
    return { rows: list, total: Number(response.headers.get('X-Total-Count') ?? list.length) };
  }
  async function show(limit = PAGE) { const first = await bring(0, limit); setRows(first.rows); setTotal(first.total); return first.rows; }
  return {
    rows, total,
    /** A new question: its conditions (already in stored form) replace the earlier ones. */
    query: async (parameters: Record<string, string>) => { asked.current = { ...asked.current, parameters }; return show(); },
    /** The same question again (after saving or deleting), keeping as many rows as were on screen. */
    refresh: async () => show(Math.max(PAGE, Math.min(rows.length, 5000))),
    more: async () => { const next = await bring(rows.length, PAGE); setRows(previous => [...previous, ...next.rows]); setTotal(next.total); },
    /** key: the column asked for; screens map shown columns (statusLabel, updatedAt ...) to what the server orders by. */
    sortBy: async (sort: ListSort) => { asked.current = { ...asked.current, sort: sort ?? initialSort }; await show(); },
    /** Every row the conditions match (up to 100,000), for a file. */
    all: async () => (rows.length >= (total ?? 0) ? rows : (await bring(0, 100000)).rows),
  };
}

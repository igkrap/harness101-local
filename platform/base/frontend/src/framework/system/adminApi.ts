import { apiFetch } from '../auth/sessionClient';

/** Calls a system administration API and returns its JSON; a refusal becomes an Error with the server's message. */
export async function adminApi<T = unknown>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await apiFetch(path, { method, headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await response.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!response.ok) {
    const detail = data && typeof data === 'object' ? (data as Record<string, unknown>) : {};
    const message = typeof detail.detail === 'string' ? detail.detail : typeof detail.message === 'string' ? detail.message : typeof detail.error === 'string' ? detail.error : '';
    throw new Error(message && !/^[A-Z_]+$/.test(message) ? message : response.status === 403 ? '권한이 없습니다.' : `요청을 처리하지 못했습니다. (${response.status})`);
  }
  return data as T;
}

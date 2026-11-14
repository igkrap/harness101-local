// Which project this window works on: the one in the address, else the one last worked on in this browser, else the first.
const LAST = 'platform:last-project';
const asked = new URLSearchParams(window.location.search).get('project');
function remembered() { try { return window.localStorage.getItem(LAST); } catch { return null; } }
export const projectId = asked || remembered() || 'default';
try { window.localStorage.setItem(LAST, projectId); } catch { /* private window: the address still carries it */ }
if (!asked && projectId !== 'default') {      // keep the address truthful, so a copied link opens the same project
  const url = new URL(window.location.href); url.searchParams.set('project', projectId); window.history.replaceState(null, '', url);
}
/** The remembered project is gone (deleted, or another machine's): forget it and open the first one. */
export function forgetProject() { try { window.localStorage.removeItem(LAST); } catch { /* nothing kept */ }
  const url = new URL(window.location.href); url.searchParams.delete('project'); window.location.replace(url); }
export function apiUrl(path:string) {
  const url=new URL(path,window.location.origin);
  if(!url.searchParams.has('project'))url.searchParams.set('project',projectId);
  return url.pathname+url.search;
}
export async function apiFetch(path:string,init?:RequestInit){return fetch(apiUrl(path),init);}

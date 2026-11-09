export const projectId = new URLSearchParams(window.location.search).get('project') || 'default';
export function apiUrl(path:string) {
  const url=new URL(path,window.location.origin);
  if(!url.searchParams.has('project'))url.searchParams.set('project',projectId);
  return url.pathname+url.search;
}
export async function apiFetch(path:string,init?:RequestInit){return fetch(apiUrl(path),init);}

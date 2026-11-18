import type { MenuGroup, MenuNode, ScreenDefinition } from './registry';

/** A program that can be found: where it sits and the text it is found by. */
export type SearchEntry = { screen: ScreenDefinition; title: string; path: string };
export type SearchHit = SearchEntry & { score: number };
/** Optional extra ranking (e.g. an embedding search on the server): ids best first. Results are merged with BM25. */
export type SemanticRanker = (query: string, entries: SearchEntry[]) => Promise<string[]>;

const CHOSEONG = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'];
/** 품목 등록 -> ㅍㅁㄷㄹ (spaces dropped), for initial-consonant search. */
export function choseong(text: string): string {
  return [...text].map(ch => {
    const code = ch.charCodeAt(0) - 0xac00;
    return code >= 0 && code <= 11171 ? CHOSEONG[Math.floor(code / 588)] : /\s/.test(ch) ? '' : ch.toLowerCase();
  }).join('');
}

/** Words plus character bigrams: Korean compounds match on parts ("사원" finds "사원 등록", "등록" finds every 등록 screen). */
export function tokens(text: string): string[] {
  const words = text.toLowerCase().split(/[^0-9a-z가-힣]+/).filter(Boolean);
  const out = [...words];
  // Bigrams only for Korean words; codes and latin words stay whole (MST0002 must not match every MST code).
  for (const word of words) if (/[가-힣]/.test(word)) for (let i = 0; i + 2 <= word.length; i++) out.push(word.slice(i, i + 2));
  return out;
}

export function searchEntries(groups: MenuGroup[]): SearchEntry[] {
  const seen = new Set<string>();
  const out: SearchEntry[] = [];
  const walk = (nodes: MenuNode[], path: string[]) => nodes.forEach(node => {
    if (node.children) return walk(node.children, [...path, node.title]);
    if (node.screen && !seen.has(node.screen.id)) { seen.add(node.screen.id); out.push({ screen: node.screen, title: node.title, path: path.filter(Boolean).join(' › ') }); }
  });
  groups.forEach(group => walk(group.nodes, [group.key === '__home' ? '' : group.title]));
  return out;
}

/** Program codes are internal: they are neither searched nor shown. BM25 over title, menu path and keywords, plus substring and initial-consonant matches on the title. */
export function searchPrograms(query: string, entries: SearchEntry[], limit = 12): SearchHit[] {
  const q = query.trim();
  if (!q) return [];
  const docs = entries.map(entry => tokens(`${entry.title} ${entry.title} ${entry.path} ${(entry.screen.meta.keywords ?? []).join(' ')}`));
  const average = docs.reduce((sum, doc) => sum + doc.length, 0) / Math.max(docs.length, 1);
  const frequency = new Map<string, number>();
  docs.forEach(doc => new Set(doc).forEach(token => frequency.set(token, (frequency.get(token) ?? 0) + 1)));
  const terms = [...new Set(tokens(q))];
  const initials = /^[ㄱ-ㅎ]+$/.test(q.replace(/\s/g, '')) ? q.replace(/\s/g, '') : '';
  const K1 = 1.2, B = 0.75;
  return entries.map((entry, index) => {
    const doc = docs[index];
    let score = 0;
    for (const term of terms) {
      const tf = doc.filter(token => token === term).length;
      if (!tf) continue;
      const idf = Math.log(1 + (entries.length - (frequency.get(term) ?? 0) + 0.5) / ((frequency.get(term) ?? 0) + 0.5));
      score += idf * (tf * (K1 + 1)) / (tf + K1 * (1 - B + B * doc.length / (average || 1)));
    }
    const title = entry.title.toLowerCase();
    if (title.includes(q.toLowerCase())) score += title.startsWith(q.toLowerCase()) ? 3 : 2;
    if (initials && choseong(entry.title).includes(initials)) score += choseong(entry.title).startsWith(initials) ? 3 : 2;
    if ((entry.screen.meta.keywords ?? []).some(word => word.toLowerCase().includes(q.toLowerCase()))) score += 1.5;
    return { ...entry, score };
  }).filter(hit => hit.score > 0).sort((a, b) => b.score - a.score || a.title.localeCompare(b.title, 'ko')).slice(0, limit);
}

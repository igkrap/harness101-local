import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { Button, Dialog } from '../ui';
import { useWorkspaceNav } from '../workspace/navContext';

/**
 * Going from one screen to another with something in hand: "the shipments of this order", "the orders behind this figure".
 * The screen that sends puts conditions (and the words for them) into the workspace's intent for the other screen;
 * the screen that receives lists by them and shows them above its list, where they can be let go of.
 */
export type Linked = { /** List conditions in stored form: field -> value, <date>_from/_to, lines.<field>, status. */ params: Record<string, string>;
  /** What they mean, in the sender's words: "수주 SO-2611-0002 의 출하". */ note: string; /** A record to open at once. */ select?: string };

export function intentOf(linked: Linked): Record<string, string> {
  return { query: JSON.stringify(linked.params), note: linked.note, ...(linked.select ? { select: linked.select } : {}) };
}

/** What another screen sent this one (null when nothing, or after it was let go of). `at` changes with every sending. */
export function useLinked(programCode: string | undefined): { linked: Linked | null; at: number; release: () => void } {
  const intent = useWorkspaceNav()?.intents[programCode ?? ''];
  const [released, setReleased] = useState(0);
  const at = intent?.at ?? 0;
  let linked: Linked | null = null;
  if (intent && at !== released && (intent.values.query || intent.values.select)) {
    try { linked = { params: JSON.parse(intent.values.query || '{}') as Record<string, string>, note: intent.values.note || '', select: intent.values.select }; } catch { linked = null; }
  }
  return { linked, at, release: () => setReleased(at) };
}

/** The line above a list that says which conditions came from another screen. */
export function LinkedNote({ linked, onRelease }: { linked: Linked | null; onRelease: () => void }) {
  if (!linked || !Object.keys(linked.params).length) return null;
  return <div className="fw-linked" data-ui="linked-note" role="status">
    <span className="fw-linked-mark">연결 조건</span><span>{linked.note || Object.entries(linked.params).map(([name, value]) => `${name} = ${value}`).join(', ')}</span>
    <Button label="해제" variant="ghost" icon="small-cross" onClick={onRelease} />
  </div>;
}

type Link = { entity: string; title: string; programCode: string; field: string; label: string; count: number; id?: number; name?: string };
/**
 * What one record is tied to: the records of other screens that use it (with how many) and the records it points at.
 * Choosing one opens that screen on exactly those records. Screens the person may not use are shown without a way in.
 */
export function LinksDialog({ api, id, title, name, isOpen, onClose }: { /** The record's API, e.g. /api/data/sales_order */ api: string; id: string | null; title: string;
  /** How the record reads, for the note on the other screen: "수주 SO-2611-0002". */ name: string; isOpen: boolean; onClose: () => void }) {
  const nav = useWorkspaceNav();
  const [links, setLinks] = useState<{ from: Link[]; to: Link[] } | null>(null);
  const [problem, setProblem] = useState('');
  const asked = useRef(0);
  useEffect(() => {
    if (!isOpen || !id) return;
    const turn = ++asked.current;
    setLinks(null); setProblem('');
    void apiFetch(`${api}/${id}/links`).then(async response => {
      if (turn !== asked.current) return;
      if (response.ok) setLinks(await response.json() as { from: Link[]; to: Link[] }); else setProblem('연결된 자료를 읽지 못했습니다.');
    }).catch(() => { if (turn === asked.current) setProblem('연결된 자료를 읽지 못했습니다.'); });
  }, [api, id, isOpen]);
  const usable = new Set((nav?.groups ?? []).flatMap(group => JSON.stringify(group).match(/APP\d{4}/g) ?? []));
  const go = (link: Link, linked: Linked) => { nav?.open(link.programCode, intentOf(linked)); onClose(); };
  const row = (link: Link, text: string, linked: Linked, key: string) => <li key={key}>
    <span>{text}</span>
    {nav && usable.has(link.programCode) ? <Button label={`${link.title} 열기`} outlined icon="arrow-top-right" onClick={() => go(link, linked)} /> : <span className="fw-links-none">이 화면을 쓸 권한이 없습니다</span>}
  </li>;
  return <Dialog isOpen={isOpen} onClose={onClose} title={`${name || title} 연결 자료`} width={640} footer={<Button label="닫기" onClick={onClose} />}>
    <div data-ui="record-links" className="fw-links">
      {problem && <div role="alert">{problem}</div>}
      {!problem && !links && <div className="fw-history-empty">불러오는 중…</div>}
      {links && <>
        <h4>이 자료를 쓰는 곳</h4>
        {links.from.length === 0 ? <div className="fw-history-empty">다른 화면에서 이 자료를 쓰는 건이 없습니다.</div>
          : <ul>{links.from.map(link => row(link, `${link.title} ${link.count.toLocaleString('en-US')}건 (${link.label})`, { params: { [link.field]: String(id) }, note: `${name} 을(를) 쓰는 ${link.title}` }, `${link.entity}:${link.field}`))}</ul>}
        <h4>이 자료가 가리키는 것</h4>
        {links.to.length === 0 ? <div className="fw-history-empty">다른 화면의 자료를 가리키는 항목이 없습니다.</div>
          : <ul>{links.to.map(link => row(link, `${link.label}: ${link.name ?? ''}`, { params: {}, note: '', select: String(link.id) }, `${link.entity}:${link.label}`))}</ul>}
      </>}
    </div>
  </Dialog>;
}

import { useEffect, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { Dialog, Button, ContentButton, Tag } from '../ui';
import { formatDateTime } from '../gridExport';
import { useWorkspaceNav } from './navContext';

type Notice = { id: number; title: string; pinned: boolean; published?: boolean; writer: string; createdAt: string; body?: string };
const NOTICE_PROGRAM = 'SYS0009', STEP_MS = 4000;

/**
 * Recent notice titles, one at a time, rotating. Clicking one goes straight to the post: the 게시판 screen when the
 * user may open it, otherwise the post in a window.
 */
export function NoticeTicker() {
  const nav = useWorkspaceNav();
  const [notices, setNotices] = useState<Notice[]>([]);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [reading, setReading] = useState<Notice | null>(null);
  // Live: the server says when posts change (server-sent events) and the titles are read again at once, so a new
  // notice appears without a refresh. A slow poll and the window regaining focus cover a dropped connection.
  useEffect(() => {
    let alive = true;
    const known = new Set<number>();
    const load = () => void apiFetch('/api/auth/posts?type=NOTICE&size=8').then(async response => {
      if (!response.ok || !alive) return;
      const items = (((await response.json()) as { items: Notice[] }).items ?? []).filter(notice => notice.published !== false);
      const fresh = known.size > 0 ? items.findIndex(notice => !known.has(notice.id)) : -1;
      items.forEach(notice => known.add(notice.id));
      setNotices(items);
      if (fresh >= 0) setIndex(fresh);  // show the new notice first
    }).catch(() => {});
    load();
    const stream = typeof EventSource === 'undefined' ? null : new EventSource('/api/auth/events');
    stream?.addEventListener('posts', load);
    const timer = window.setInterval(load, 60000);
    window.addEventListener('focus', load);
    return () => { alive = false; stream?.close(); window.clearInterval(timer); window.removeEventListener('focus', load); };
  }, []);
  useEffect(() => {
    if (paused || notices.length < 2) return;
    const timer = window.setInterval(() => setIndex(value => (value + 1) % notices.length), STEP_MS);
    return () => window.clearInterval(timer);
  }, [paused, notices.length]);
  if (!notices.length) return <div className="home-hint">화면 이름이나 초성을 입력하고 ↑↓ 로 선택해 Enter 로 엽니다</div>;
  const shown = notices.filter(notice => notice.published !== false);
  if (!shown.length) return <div className="home-hint">화면 이름이나 초성을 입력하고 ↑↓ 로 선택해 Enter 로 엽니다</div>;
  const current = shown[index % shown.length];
  const canOpenScreen = Boolean(nav?.groups.some(group => hasProgram(group.nodes)));
  async function open(notice: Notice) {
    if (nav && canOpenScreen) return nav.open(NOTICE_PROGRAM, { post: String(notice.id) });
    const response = await apiFetch(`/api/auth/posts/${notice.id}`);
    if (response.ok) setReading(await response.json());
  }
  return <>
    <div className="home-notice" data-ui="notice-ticker" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
      <Tag minimal intent="primary" round>공지</Tag>
      <ContentButton key={current.id} className="home-notice-title" onClick={() => void open(current)} label={`공지사항: ${current.title}`}>
        <span className="home-notice-text">{current.pinned && '📌 '}{current.title}</span>
      </ContentButton>
      {shown.length > 1 && <span className="home-notice-count" aria-hidden="true">{index % shown.length + 1}/{shown.length}</span>}
    </div>
    <Dialog isOpen={Boolean(reading)} onClose={() => setReading(null)} title={reading?.title ?? ''} width={560} footer={<Button label="닫기" onClick={() => setReading(null)} />}>
      <div style={{ fontSize: 12, color: 'var(--fw-muted)', marginBottom: 10 }}>{reading?.writer} · {formatDateTime(reading?.createdAt)}</div>
      <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{reading?.body}</div>
    </Dialog>
  </>;
}

type Node = { screen?: { id: string }; children?: Node[] };
function hasProgram(nodes: Node[]): boolean { return nodes.some(node => node.screen?.id === NOTICE_PROGRAM || hasProgram(node.children ?? [])); }

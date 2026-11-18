import { useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch } from '../auth/sessionClient';
import { BigSearchInput, Card, ContentButton, Icon, Tag } from '../ui';
import { formatDateTime } from '../gridExport';
import { searchEntries, searchPrograms } from './menuSearch';
import { useWorkspaceNav } from './navContext';
import { NoticeTicker } from './NoticeTicker';
import { HomeBackdrop } from './HomeBackdrop';
import './HomePage.css';

const DOTS = ['#7c6cf0', '#e84fa8', '#ef5b5b', '#2bb673', '#f2b53c', '#3d9bf0'];
const dotColor = (id: string) => DOTS[[...id].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 7) % DOTS.length];

/**
 * The home page: one search box in the middle (find a program by name, menu path, keywords or initial
 * consonants and open it), with the user's favourites, recently opened programs and things waiting for them below.
 */
export function HomePage() {
  const nav = useWorkspaceNav();
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const [recent, setRecent] = useState<{ programCode: string; openedAt: string }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const entries = useMemo(() => searchEntries(nav?.groups ?? []).filter(entry => entry.screen.meta.code), [nav?.groups]);
  const hits = useMemo(() => searchPrograms(query, entries, 8), [query, entries]);
  useEffect(() => { setCursor(0); }, [query]);
  useEffect(() => {
    void apiFetch('/api/auth/recent-programs').then(async response => { if (response.ok) setRecent(await response.json()); }).catch(() => {});
  }, []);
  if (!nav) return <h1 className="home-title">홈</h1>;
  const open = (id: string) => { setQuery(''); nav.open(id); };
  const byId = (id: string) => entries.find(entry => entry.screen.id === id);
  const favorites = nav.favorites.flatMap(id => { const entry = byId(id); return entry ? [entry] : []; });
  const recents = recent.flatMap(item => { const entry = byId(item.programCode); return entry ? [{ entry, at: item.openedAt }] : []; }).slice(0, 8);
  const waiting = Object.entries(nav.badges).flatMap(([id, count]) => { const entry = byId(id); return entry && count > 0 ? [{ entry, count }] : []; });
  const chip = (id: string, title: string, extra?: string) => <ContentButton key={id} outlined className="home-chip" onClick={() => open(id)}>
    <span className="home-dot" style={{ background: dotColor(id) }} /><span className="home-chip-title">{title}</span>{extra && <small>{extra}</small>}
  </ContentButton>;
  return <div className="home" data-ui="home">
    <div className="home-backdrop" aria-hidden="true" />
    <HomeBackdrop />
    <h1 className="home-title">홈</h1>
    <div className="home-hero">
      {nav.logo ? <img src={nav.logo} alt="" className="home-logo" /> : <span className="home-logo home-logo-mark" aria-hidden="true">{nav.systemName.slice(0, 1)}</span>}
      <div className="home-date">{`${formatDateTime(new Date()).slice(0, 10)} (${'일월화수목금토'[new Date().getDay()]})`} · {nav.systemName}</div>
      <div className="home-greeting"><span className="home-name">{nav.userName}</span>님, 무엇을 할까요?</div>
      <div className="home-search" role="search">
        <BigSearchInput inputRef={input} aria-label="통합 검색" placeholder="화면 이름, 업무, 초성으로 찾기 (예: 사원, 부서 등록, ㅍㅁ)" value={query} autoFocus
          role="combobox" aria-expanded={Boolean(query.trim())} aria-controls="home-results" aria-activedescendant={hits[cursor] ? `home-hit-${cursor}` : undefined}
          onChange={setQuery}
          onKeyDown={event => {
            if (event.key === 'ArrowDown') { event.preventDefault(); setCursor(value => Math.min(value + 1, Math.max(hits.length - 1, 0))); }
            else if (event.key === 'ArrowUp') { event.preventDefault(); setCursor(value => Math.max(value - 1, 0)); }
            else if (event.key === 'Enter' && hits[cursor]) { event.preventDefault(); open(hits[cursor].screen.id); }
            else if (event.key === 'Escape') setQuery('');
          }} />
        <kbd className="home-kbd">Enter</kbd>
      </div>
      {query.trim() && <ul id="home-results" role="listbox" aria-label="검색 결과" className="home-results">
        {hits.map((hit, index) => <li key={hit.screen.id} id={`home-hit-${index}`} role="option" aria-selected={index === cursor}
          className={index === cursor ? 'is-active' : undefined} onMouseEnter={() => setCursor(index)} onClick={() => open(hit.screen.id)}>
          <span className="home-dot" style={{ background: dotColor(hit.screen.id) }} />
          <span className="home-hit-title">{hit.title}</span><small>{hit.path}</small>
        </li>)}
        {hits.length === 0 && <li className="home-empty">찾는 화면이 없습니다. 다른 낱말로 찾아보세요.</li>}
      </ul>}
      {!query.trim() && <NoticeTicker />}
    </div>
    <div className="home-cards">
      <Card label="즐겨찾기" className="home-card"><h2><span className="home-badge is-star"><Icon name="star" size={14} /></span>즐겨찾기</h2>
        {favorites.length ? <div className="home-chips">{favorites.map(entry => chip(entry.screen.id, entry.title))}</div>
          : <p className="home-empty">자주 쓰는 화면의 ☆를 누르면 여기에 모입니다.</p>}</Card>
      <Card label="최근에 연 화면" className="home-card"><h2><span className="home-badge"><Icon name="history" size={14} /></span>최근에 연 화면</h2>
        {recents.length ? <div className="home-chips">{recents.map(item => chip(item.entry.screen.id, item.entry.title, formatDateTime(item.at).slice(5)))}</div>
          : <p className="home-empty">아직 연 화면이 없습니다.</p>}</Card>
      {waiting.length > 0 && <Card label="처리할 일" className="home-card"><h2><span className="home-badge is-alert"><Icon name="notifications" size={14} /></span>처리할 일</h2>
        <div className="home-chips">{waiting.map(item => <ContentButton key={item.entry.screen.id} outlined className="home-chip" onClick={() => open(item.entry.screen.id)}>
          <span className="home-chip-title">{item.entry.title}</span><Tag round intent="primary">{item.count}</Tag></ContentButton>)}</div></Card>}
    </div>
  </div>;
}

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Button, ContentButton, MenuItem, PopoverMenu, SearchInput, Tag, Tooltip, Tree, type TreeNode } from '../ui';
import type { MenuGroup, MenuNode } from './registry';
import { MenuIcon } from './menuIcons';
import { searchEntries, searchPrograms } from './menuSearch';
import './WorkspaceSidebar.css';

export type WorkspaceSidebarProps = {
  /** 홈('__home'), one group per 모듈(module) with its 메뉴 tree, and '__unassigned' for unplaced screens. */
  groups: MenuGroup[];
  /** Logo image (data: URL); empty shows the initial of the system name. */
  logo?: string;
  collapsed: boolean;
  onCollapsedChange: (value: boolean) => void;
  active: string;
  onOpen: (id: string) => void;
  title: string;
  userLabel: string;
  /** Second line of the user card (login id). */
  userName?: string;
  /** Counts shown as a badge on a program (by program code), e.g. sign-ups waiting for approval. */
  badges?: Record<string, number>;
  /** Program ids the user starred, and the toggle. */
  favorites?: readonly string[];
  onFavorite?: (id: string, on: boolean) => void;
  /** Opens 내 정보 (own name, e-mail, password). */
  onAccount?: () => void;
  onLogout: () => void;
};

const DOTS = ['#7c6cf0', '#e84fa8', '#ef5b5b', '#2bb673', '#f2b53c', '#3d9bf0'];
// A program keeps one colour wherever it appears (menu, favourites, search).
const dotColor = (id: string) => DOTS[[...id].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 7) % DOTS.length];
const contains = (nodes: MenuNode[], id: string): boolean => nodes.some(node => node.screen?.id === id || contains(node.children ?? [], id));
const folderKeys = (nodes: MenuNode[]): string[] => nodes.flatMap(node => node.children ? [node.key, ...folderKeys(node.children)] : []);
const programs = (nodes: MenuNode[]): MenuNode[] => nodes.flatMap(node => node.children ? programs(node.children) : node.screen ? [node] : []);

/**
 * Dark sidebar built from Blueprint parts (dark theme): logo, system name, collapse; program search; 홈, the chosen
 * module's menu as a Tree, unplaced programs; the modules as icon buttons; the user card. Collapsed it is a rail of
 * icon buttons with tooltips.
 */
export function WorkspaceSidebar({ groups, logo, collapsed, onCollapsedChange, active, onOpen, title, userLabel, userName, badges = {}, favorites = [], onFavorite, onAccount, onLogout }: WorkspaceSidebarProps) {
  const home = groups.find(group => group.key === '__home');
  const unassigned = groups.find(group => group.key === '__unassigned');
  const modules = groups.filter(group => group !== home && group !== unassigned);
  const owner = modules.find(group => contains(group.nodes, active))?.key;
  const [picked, setPicked] = useState(owner ?? modules[0]?.key ?? '');
  useEffect(() => { if (owner) setPicked(owner); }, [owner]);  // opening a screen elsewhere (tab, link) follows it
  const current = modules.find(group => group.key === picked) ?? modules[0];
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) => setClosed(previous => { const next = new Set(previous); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const currentFolders = current ? folderKeys(current.nodes) : [];
  // Program search across every module (BM25 over name, code, menu path and keywords; initial consonants too).
  const [query, setQuery] = useState('');
  const entries = useMemo(() => searchEntries(groups), [groups]);
  const hits = useMemo(() => searchPrograms(query, entries), [query, entries]);
  const openHit = (id: string) => { onOpen(id); setQuery(''); };
  const iconName = (node: MenuNode) => node.icon ?? node.screen?.meta.icon ?? (node.screen?.meta.code ? 'document' : 'home');
  // Favourites: only programs the user may open, in the order they were starred.
  const everyProgram = groups.flatMap(group => programs(group.nodes));
  const starred = favorites.flatMap(id => { const node = everyProgram.find(item => item.screen?.id === id); return node ? [{ ...node, key: `fav:${id}` }] : []; });
  const star = (id: string) => onFavorite && <Button isIconOnly size="sm" variant="ghost" className={favorites.includes(id) ? 'fw-star is-on' : 'fw-star'}
    label={favorites.includes(id) ? '즐겨찾기 해제' : '즐겨찾기 추가'} aria-pressed={favorites.includes(id)} icon={favorites.includes(id) ? 'star' : 'star-empty'}
    onClick={event => { event.stopPropagation(); onFavorite(id, !favorites.includes(id)); }} />;
  // Programs show a coloured dot (an icon only if one was chosen in 메뉴 편성); folders and 홈 show icons.
  const mark = (node: MenuNode) => node.icon || !node.screen?.meta.code
    ? <span className="bp6-tree-node-icon"><MenuIcon name={iconName(node)} /></span>
    : <span className="bp6-tree-node-icon ws-dot-box"><span className="ws-dot" style={{ background: dotColor(node.screen.id) }} /></span>;
  const badge = (code: string) => badges[code] ? <Tag round intent="primary" label={`${badges[code]}건`}>{badges[code]}</Tag> : undefined;
  // Blueprint tree nodes; each label is a real button so the menu works from the keyboard.
  const toNodes = (nodes: MenuNode[]): TreeNode<MenuNode>[] => nodes.map(node => node.children
    ? { id: node.key, nodeData: node, hasCaret: true, isExpanded: !closed.has(node.key), childNodes: toNodes(node.children),
        icon: <span className="bp6-tree-node-icon"><MenuIcon name={node.icon || 'folder'} /></span>,
        label: <button type="button" className="ws-node" aria-expanded={!closed.has(node.key)}>{node.title}</button> }
    : { id: node.key, nodeData: node, isSelected: active === node.screen?.id,
        secondaryLabel: node.screen && <>{badge(node.screen.id)}{node.screen.meta.code && star(node.screen.id)}</>,
        icon: mark(node),
        label: <button type="button" className="ws-node" aria-current={active === node.screen?.id ? 'page' : undefined}>{node.title}</button> });
  const click = (node: TreeNode<MenuNode>) => { const data = node.nodeData; if (data?.children) toggle(data.key); else if (data?.screen) onOpen(data.screen.id); };
  const toggleNode = (node: TreeNode<MenuNode>) => { if (node.nodeData) toggle(node.nodeData.key); };
  const menu = (nodes: MenuNode[]) => <Tree nodes={toNodes(nodes)} onClick={click} onToggle={toggleNode} />;
  // Collapsed: a short rail, not the whole menu. 홈, a search button, 즐겨찾기 and each top folder as one icon that
  // opens its programs in a menu beside the rail; loose programs gather under one "기타" icon.
  const dotOf = (id: string) => <span className="ws-dot-box"><span className="ws-dot" style={{ background: dotColor(id) }} /></span>;
  const items = (nodes: MenuNode[]): ReactNode => nodes.map(node => node.children
    ? <MenuItem key={node.key} text={node.title} icon={<MenuIcon name={node.icon || 'folder'} />}>{items(node.children)}</MenuItem>
    : node.screen && <MenuItem key={node.key} text={node.title} active={active === node.screen.id} icon={dotOf(node.screen.id)} onClick={() => onOpen(node.screen!.id)} />);
  const flyout = (key: string, label: string, icon: string, nodes: MenuNode[]) => nodes.length > 0 && <PopoverMenu key={key}
    trigger={<Button label={label} isIconOnly variant="ghost" isActive={contains(nodes, active)} icon={<MenuIcon name={icon} />} />}>{items(nodes)}</PopoverMenu>;
  const loose = [...(current?.nodes.filter(node => !node.children) ?? []), ...(unassigned?.nodes ?? [])];
  const railView = <div className="ws-rail">
    {home?.nodes.map(node => node.screen && <Tooltip key={node.key} text={node.title}><Button label={node.title} isIconOnly variant="ghost"
      isActive={active === node.screen.id} icon={<MenuIcon name="home" />} onClick={() => onOpen(node.screen!.id)} /></Tooltip>)}
    <Tooltip text="프로그램 검색"><Button label="프로그램 검색 열기" isIconOnly variant="ghost" icon="search" onClick={() => onCollapsedChange(false)} /></Tooltip>
    {flyout('fav', '즐겨찾기', 'star', starred)}
    {current?.nodes.filter(node => node.children).map(node => flyout(node.key, node.title, node.icon || 'folder', node.children!))}
    {flyout('loose', '기타 프로그램', 'more', loose)}
  </div>;

  return <aside className={collapsed ? 'workspace-sidebar bp6-dark is-collapsed' : 'workspace-sidebar bp6-dark'} data-ui="workspace-sidebar">
    <div className="ws-head">
      {!collapsed && <>
        {logo ? <img src={logo} alt="" className="ws-logo" /> : <span className="ws-logo ws-logo-mark" aria-hidden="true">{title.slice(0, 1)}</span>}
        <strong className="ws-title">{title}</strong>
      </>}
      <Button label={collapsed ? '사이드바 펼치기' : '사이드바 접기'} isIconOnly variant="ghost" aria-expanded={!collapsed}
        icon={collapsed ? 'double-chevron-right' : 'double-chevron-left'} onClick={() => onCollapsedChange(!collapsed)} />
    </div>
    {!collapsed && <div className="ws-search">
      <SearchInput label="프로그램 검색" placeholder="프로그램 검색" value={query} onChange={setQuery}
        onEnter={() => { if (hits[0]) openHit(hits[0].screen.id); }} onEscape={() => setQuery('')} />
    </div>}
    <nav aria-label="메뉴" className="ws-nav">
      {collapsed ? railView : query.trim() ? <div role="group" aria-label="검색 결과">
        <div className="ws-section">검색 결과 {hits.length}건</div>
        <Tree<string> onToggle={() => undefined} onClick={node => { if (node.nodeData) openHit(node.nodeData); }} nodes={hits.map(hit => ({
          id: hit.screen.id, nodeData: hit.screen.id, isSelected: active === hit.screen.id,
          icon: hit.screen.meta.code ? <span className="bp6-tree-node-icon ws-dot-box"><span className="ws-dot" style={{ background: dotColor(hit.screen.id) }} /></span>
            : <span className="bp6-tree-node-icon"><MenuIcon name="home" /></span>,
          label: <button type="button" className="ws-node">{hit.title}</button>, secondaryLabel: hit.path ? <small>{hit.path}</small> : undefined }))} />
        {hits.length === 0 && <div className="ws-empty">찾는 프로그램이 없습니다.</div>}
      </div> : <>
        {home && menu(home.nodes)}
        <div role="group" aria-label="즐겨찾기">
          <div className="ws-section">즐겨찾기</div>
          {starred.length ? menu(starred) : <div className="ws-empty">메뉴의 ☆를 누르면 여기에 모입니다.</div>}
        </div>
        <div className="ws-section">
          <span>{current?.title ?? '메뉴'}</span>
          {currentFolders.length > 0 && <span className="ws-tools">
            <Button label="폴더 전체 펼치기" isIconOnly size="sm" variant="ghost" icon="expand-all"
              onClick={() => setClosed(previous => new Set([...previous].filter(key => !currentFolders.includes(key))))} />
            <Button label="폴더 전체 접기" isIconOnly size="sm" variant="ghost" icon="collapse-all"
              onClick={() => setClosed(previous => new Set([...previous, ...currentFolders]))} />
          </span>}
        </div>
        {current && <div role="group" aria-label={current.title}>{menu(current.nodes)}</div>}
        {unassigned && <div role="group" aria-label={unassigned.title}>
          <div className="ws-section">{unassigned.title}</div>
          {menu(unassigned.nodes)}
        </div>}
      </>}
    </nav>
    {modules.length > 0 && <div role="toolbar" aria-label="모듈" className="ws-modules">
      {modules.map(group => <Tooltip key={group.key} text={group.title} placement={collapsed ? 'right' : 'top'}>
        <Button label={group.title} isIconOnly variant="ghost" isActive={current?.key === group.key} aria-pressed={current?.key === group.key}
          icon={<MenuIcon name={group.icon ?? 'list'} />} onClick={() => setPicked(group.key)} /></Tooltip>)}
    </div>}
    <div className="ws-user">
      <Tooltip text="내 정보" placement={collapsed ? 'right' : 'top'}><ContentButton className="ws-account" label="내 정보" onClick={onAccount}>
        <span className="ws-avatar" aria-hidden="true">{userLabel.slice(0, 1)}</span>
        {!collapsed && <span className="ws-user-names"><strong>{userLabel}</strong>{userName && <span>{userName}</span>}</span>}
      </ContentButton></Tooltip>
      <Tooltip text="로그아웃" placement={collapsed ? 'right' : 'top'}><Button label="로그아웃" isIconOnly variant="ghost" icon="log-out" onClick={onLogout} /></Tooltip>
    </div>
  </aside>;
}

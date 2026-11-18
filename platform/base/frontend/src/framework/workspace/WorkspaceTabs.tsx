import { useEffect, useRef, useState } from 'react';
import { Button, MenuDivider, MenuItem, PopoverMenu, TabList } from '../ui';
import type { ScreenRegistry } from './registry';
import './WorkspaceTabs.css';

export type WorkspaceTabsProps = { screens: ScreenRegistry; tabs: string[]; active: string; dirty: ReadonlySet<string>; onSelect: (id: string) => void; onClose: (id: string) => void;
  /** Close several tabs at once (the tab menu). */ onCloseMany?: (ids: string[]) => void;
  /** Move tab `id` to the place of tab `target` (drag a tab onto another). */ onMove?: (id: string, target: string) => void;
  favorites?: readonly string[]; onFavorite?: (id: string, on: boolean) => void };
/**
 * Open screens as Blueprint tabs: each tab is followed by its own close button (siblings, both reachable).
 * Drag a tab onto another to reorder. Right end: favourite star and the tab menu (close others/left/right/all, open tab list).
 */
export function WorkspaceTabs({ screens, tabs, active, dirty, onSelect, onClose, onCloseMany, onMove, favorites = [], onFavorite }: WorkspaceTabsProps) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const titleOf = (id: string) => screens[id]?.meta.title ?? id;
  const index = tabs.indexOf(active);
  const closeMany = (ids: string[]) => { if (ids.length) (onCloseMany ?? (list => list.forEach(onClose)))(ids); };
  // Only the tabs scroll sideways; the star and the tab menu stay at the right end. The selected tab is brought into view.
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const tab = bar.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
    const tools = bar.current?.querySelector<HTMLElement>('.workspace-tab-tools');
    if (!tab || !bar.current) return;
    const view = bar.current.getBoundingClientRect(), box = tab.getBoundingClientRect(), right = view.right - (tools?.offsetWidth ?? 0) - 40;
    if (box.left < view.left) bar.current.scrollLeft -= view.left - box.left + 12;
    else if (box.right > right) bar.current.scrollLeft += box.right - right;
  }, [active, tabs.length]);
  // Arrows appear only when the tabs do not fit; each is disabled at its end.
  const [room, setRoom] = useState({ left: false, right: false });
  useEffect(() => {
    const element = bar.current;
    if (!element) return;
    const measure = () => setRoom(previous => {
      const next = { left: element.scrollLeft > 1, right: element.scrollLeft < element.scrollWidth - element.clientWidth - 1 };
      return next.left === previous.left && next.right === previous.right ? previous : next;
    });
    measure();
    element.addEventListener('scroll', measure, { passive: true });
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => { element.removeEventListener('scroll', measure); observer.disconnect(); };
  }, [tabs.length, active]);
  const slide = (by: number) => bar.current?.scrollBy({ left: by, behavior: 'smooth' });
  return <div data-ui="workspace-tabs" className="workspace-tabs" ref={bar}
    onWheel={event => { if (bar.current && !event.shiftKey && Math.abs(event.deltaY) > Math.abs(event.deltaX)) bar.current.scrollLeft += event.deltaY; }}>
    <TabList id="workspace" selected={active} onSelect={onSelect} tabs={tabs.map(id => {
      const title = titleOf(id);
      return { id, title: <span className={over === id && dragging && dragging !== id ? 'workspace-tab-title is-drop' : 'workspace-tab-title'} draggable={Boolean(onMove)}
          onDragStart={event => { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', id); setDragging(id); }}
          onDragOver={event => { if (dragging) { event.preventDefault(); setOver(id); } }}
          onDrop={event => { event.preventDefault(); if (dragging) onMove?.(dragging, id); setDragging(null); setOver(null); }}
          onDragEnd={() => { setDragging(null); setOver(null); }}>{title}{dirty.has(id) && <span aria-label="저장하지 않은 변경"> •</span>}</span>,
        after: <Button className="workspace-tab-close" label={`${title} 닫기`} isIconOnly icon="small-cross" variant="ghost" size="sm" onClick={() => onClose(id)} /> };
    })} end={<span className="workspace-tab-tools">
      {(room.left || room.right) && <>
        <Button isIconOnly variant="ghost" label="왼쪽 탭 보기" icon="chevron-left" isDisabled={!room.left} onClick={() => slide(-240)} />
        <Button isIconOnly variant="ghost" label="오른쪽 탭 보기" icon="chevron-right" isDisabled={!room.right} onClick={() => slide(240)} />
      </>}
      {onFavorite && screens[active]?.meta.code && <Button isIconOnly variant="ghost" aria-pressed={favorites.includes(active)}
        label={favorites.includes(active) ? '즐겨찾기 해제' : '즐겨찾기 추가'} icon={favorites.includes(active) ? 'star' : 'star-empty'}
        className={favorites.includes(active) ? 'fw-star is-on' : 'fw-star'} onClick={() => onFavorite(active, !favorites.includes(active))} />}
      <PopoverMenu placement="bottom-end" trigger={<Button isIconOnly variant="ghost" label="탭 메뉴" icon="more" />}>
        <MenuItem text="현재 탭 닫기" disabled={!active} onClick={() => onClose(active)} />
        <MenuItem text="현재 탭 외 모두 닫기" disabled={tabs.length < 2} onClick={() => closeMany(tabs.filter(id => id !== active))} />
        <MenuItem text="왼쪽 탭 닫기" disabled={index <= 0} onClick={() => closeMany(tabs.slice(0, index))} />
        <MenuItem text="오른쪽 탭 닫기" disabled={index < 0 || index >= tabs.length - 1} onClick={() => closeMany(tabs.slice(index + 1))} />
        <MenuItem text="전체 탭 닫기" disabled={!tabs.length} onClick={() => closeMany(tabs)} />
        <MenuDivider title="열린 탭" />
        {tabs.map(id => <MenuItem key={id} text={titleOf(id)} active={id === active} onClick={() => onSelect(id)} />)}
      </PopoverMenu>
    </span>} />
  </div>;
}

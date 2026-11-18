import { useCallback, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Button, TabList, tabPanelId, tabTitleId } from './ui';

export type PanelTab = { id: string; label: string; content: ReactNode };
export type TabbedPanelProps = { tabs: readonly PanelTab[]; collapsed: boolean; onCollapsedChange: (value: boolean) => void; label?: string; revealForm?: { id: string; sequence: number }; selected?: string; onSelect?: (id: string) => void; body?: ReactNode };
// selected/onSelect: optional controlled tab. body: one body shared by all tabs (e.g. one form whose field groups are the tabs).

export function TabbedPanel({ tabs, collapsed, onCollapsedChange, label = '편집 패널', revealForm, selected: controlled, onSelect, body }: TabbedPanelProps) {
  const [internal, setInternal] = useState(tabs[0]?.id ?? '');
  const selected = controlled ?? internal;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const setSelected = useCallback((id: string) => { setInternal(id); onSelectRef.current?.(id); }, []);
  const active = tabs.some(tab => tab.id === selected) ? selected : tabs[0]?.id;
  const prefix = useId();
  const panels = useRef(new Map<string, HTMLDivElement>());
  useLayoutEffect(() => {
    if (!revealForm) return;
    const form = document.getElementById(revealForm.id);
    if (form) for (const [id, panel] of panels.current) if (panel.contains(form)) { setSelected(id); break; }
  }, [revealForm, setSelected]);
  function choose(id: string) {
    setSelected(id);
    onCollapsedChange(false);
  }
  return <section data-ui="tabbed-panel" aria-label={label} style={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%', border: '1px solid var(--fw-border)', borderRadius: 4, overflow: 'hidden', background: 'var(--fw-surface)' }}>
    <div style={{ flexShrink: 0, padding: '0 8px 0 12px', borderBottom: collapsed ? 0 : '1px solid var(--fw-border)' }}>
      <TabList id={prefix} tabs={tabs.map(tab => ({ id: tab.id, title: tab.label }))} selected={active ?? ''} onSelect={choose}
        end={<Button type="button" size="sm" variant="ghost" label={collapsed ? `${label} 펼치기` : `${label} 접기`} aria-expanded={!collapsed} aria-controls={`${prefix}-body`}
          onClick={() => onCollapsedChange(!collapsed)} icon={collapsed ? 'chevron-up' : 'chevron-down'} />} />
    </div>
    <div id={`${prefix}-body`} hidden={collapsed} style={{ display: collapsed ? 'none' : 'flex', flex: 1, minHeight: 0, overflow: 'auto' }}>
      {body !== undefined ? <div id={tabPanelId(prefix, active ?? '')} role="tabpanel" aria-labelledby={tabTitleId(prefix, active ?? '')}
        ref={element => { panels.current.clear(); if (element && active) panels.current.set(active, element); }}
        style={{ display: 'block', width: '100%', padding: '8px 12px', boxSizing: 'border-box' }}>{body}</div> :
      tabs.map(tab => <div key={tab.id} id={tabPanelId(prefix, tab.id)} role="tabpanel" aria-labelledby={tabTitleId(prefix, tab.id)} hidden={active !== tab.id}
        ref={element => { if (element) panels.current.set(tab.id, element); else panels.current.delete(tab.id); }}
        style={{ display: active === tab.id ? 'block' : 'none', width: '100%', padding: '8px 12px', boxSizing: 'border-box' }}>{tab.content}</div>)}
    </div>
  </section>;
}

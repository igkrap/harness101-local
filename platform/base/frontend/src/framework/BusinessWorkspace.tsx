import { useState, type ReactNode } from 'react';
import { ScreenTitle } from './ScreenTitle';
import { ScreenActions, type ScreenActionSet } from './ScreenActions';
import { TabbedPanel, type PanelTab } from './TabbedPanel';
import { Button } from './ui';
import { RecordEditor, type RecordEditorProps } from './RecordEditor';
import { GridDockContext, SharedToolbarContext } from './toolbarContext';

/** Field groups shown as editor tabs. Fields carry `group`; without one, required fields are 기본정보 and the rest 추가정보. */
const DEFAULT_EDITOR_GROUPS = [{ id: 'basic', label: '기본정보' }, { id: 'extra', label: '추가정보' }];
export type WorkspaceEditor = RecordEditorProps & { groups?: { id: string; label: string }[]; columns?: number };

export type BusinessWorkspaceProps = {
  title: string;
  actions: ScreenActionSet;
  query: ReactNode;
  results: ReactNode;
  /** Custom editor tabs. Prefer `editor`, which builds grouped tabs of one form. */
  editorTabs?: readonly PanelTab[];
  /** Standard master-data editor: one form, field groups as tabs, unframed, 3 columns. */
  editor?: WorkspaceEditor;
  editorCollapsed?: boolean;
  onEditorCollapsedChange?: (value: boolean) => void;
};

const EDITOR_MOTION = '0.3s';

function groupedEditor(editor: WorkspaceEditor) {
  // Explicit `group` wins; otherwise identity/required fields go to 기본정보 and optional ones to 추가정보.
  const fields = editor.fields.map(field => field.group ? field : { ...field, group: field.required ? 'basic' : 'extra' });
  const groups = (editor.groups ?? DEFAULT_EDITOR_GROUPS).filter(group => fields.some(field => field.group === group.id));
  return { fields, groups: groups.length ? groups : [DEFAULT_EDITOR_GROUPS[0]] };
}

export function BusinessWorkspace({ title, actions, query, results, editorTabs, editor, editorCollapsed, onEditorCollapsedChange }: BusinessWorkspaceProps) {
  const grouped = editor ? groupedEditor(editor) : null;
  const [localTab, setLocalTab] = useState(grouped?.groups[0]?.id ?? '');
  const activeGroup = grouped && grouped.groups.some(group => group.id === localTab) ? localTab : grouped?.groups[0]?.id ?? '';
  const tabs: readonly PanelTab[] = grouped ? grouped.groups.map(group => ({ id: group.id, label: group.label, content: null })) : editorTabs ?? [];
  const body = grouped && editor ? <RecordEditor {...editor} fields={grouped.fields} framed={false} columns={editor.columns ?? 3} group={activeGroup}
    onInvalid={names => { const field = grouped.fields.find(item => names.includes(item.name)); if (field?.group) setLocalTab(field.group); }} /> : undefined;
  const [localCollapsed, setLocalCollapsed] = useState(false);
  const [revealForm, setRevealForm] = useState<{ id: string; sequence: number }>();
  const collapsed = editorCollapsed ?? localCollapsed;
  function setCollapsed(value: boolean) { setLocalCollapsed(value); onEditorCollapsedChange?.(value); }
  return <SharedToolbarContext.Provider value={true}><div data-ui="business-workspace" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, width: '100%', gap: 8 }}>
    <header data-region="screen-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
      <ScreenTitle>{title}</ScreenTitle>
      <ScreenActions actions={actions} beforeAction={action => {
        if (action === 'create' || action === 'save') setCollapsed(false);
        const form = actions[action]?.form;
        if (action === 'save' && form) setRevealForm(previous => ({ id: form, sequence: (previous?.sequence ?? 0) + 1 }));
      }} />
    </header>
    <div data-region="query" style={{ flexShrink: 0 }}>{query}</div>
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <section data-region="results" style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <GridDockContext.Provider value={true}>{results}</GridDockContext.Provider>
      </section>
      {/* Grid-row transition animates to the panel's real height without measuring it. The tab panel
          stays expanded inside so its content shrinks with the area instead of vanishing first; once
          collapsed, visibility/inert keep the hidden controls away from keyboard and screen readers. */}
      {tabs.length > 0 && <div data-region="editor" inert={collapsed || undefined} style={{
        flexShrink: 0, display: 'grid', gridTemplateRows: collapsed ? '0fr' : '1fr', opacity: collapsed ? 0 : 1,
        visibility: collapsed ? 'hidden' : 'visible',
        transition: `grid-template-rows ${EDITOR_MOTION} ease, opacity ${EDITOR_MOTION} ease, visibility 0s linear ${collapsed ? EDITOR_MOTION : '0s'}`,
      }}>
        <div style={{ minHeight: 0, overflow: 'hidden' }}>
          <TabbedPanel tabs={tabs} collapsed={false} onCollapsedChange={setCollapsed} revealForm={revealForm}
            body={body} selected={grouped ? activeGroup : undefined} onSelect={grouped ? setLocalTab : undefined} />
        </div>
      </div>}
      {collapsed && tabs.length > 0 && <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 4 }}>
        <Button type="button" size="sm" label="편집 패널 펼치기" aria-expanded={false} onClick={() => setCollapsed(false)}
          icon="chevron-up" />
      </div>}
    </div>
  </div></SharedToolbarContext.Provider>;
}

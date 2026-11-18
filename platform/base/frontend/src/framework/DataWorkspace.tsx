import type { ReactNode } from 'react';
import { SplitPane } from './SplitPane';

export type DataWorkspaceProps = { query: ReactNode; results: ReactNode; editor: ReactNode };

export function DataWorkspace({ query, results, editor }: DataWorkspaceProps) {
  return <div data-ui="data-workspace" style={{ display: 'flex', flex: 1, minHeight: 0, width: '100%' }}><SplitPane initialRatio={2 / 3} primary={
    <section data-region="left" style={{ display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minWidth: 0, minHeight: 0 }}>
      <div data-region="query" style={{ flexShrink: 0 }}>{query}</div>
      <div data-region="results" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>{results}</div>
    </section>} secondary={<aside data-region="editor" style={{ minWidth: 0, overflow: 'auto' }}>{editor}</aside>} />
  </div>;
}

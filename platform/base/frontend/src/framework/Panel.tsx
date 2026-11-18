import type { ReactNode } from 'react';
import { ScreenTitle } from './ScreenTitle';
import { Card } from './ui';

export type PanelProps = { title?: string; actions?: ReactNode; children: ReactNode; compact?: boolean; framed?: boolean };
/** framed={false} drops the border and inner padding, for content already inside a container (e.g. a tab panel). */
export function Panel({ title, actions, children, compact = false, framed = true }: PanelProps) {
  const body = <>
    {(title || actions) && <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
      {title && <ScreenTitle level={3}>{title}</ScreenTitle>}{actions}
    </header>}
    {children}
  </>;
  void compact;
  return framed ? <Card style={{ minWidth: 0 }}>{body}</Card> : <section style={{ minWidth: 0 }}>{body}</section>;
}

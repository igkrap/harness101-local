import { useId, useState, type ReactNode } from 'react';
import { Button } from './ui';

export type QuerySectionsProps = { primary: ReactNode; advanced?: ReactNode; initiallyExpanded?: boolean };

export function QuerySections({ primary, advanced, initiallyExpanded = false }: QuerySectionsProps) {
  const [expanded, setExpanded] = useState(initiallyExpanded);
  const detailsId = useId();
  return <div data-ui="query-sections" style={{ display: 'grid', gap: 8, width: '100%' }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <div data-region="primary-conditions" style={{ display: 'flex', flex: 1, alignItems: 'end', gap: 12, flexWrap: 'wrap' }}>{primary}</div>
      {advanced && <Button type="button" size="sm" label={expanded ? '상세조건 접기' : '상세조건 펼치기'} aria-expanded={expanded} aria-controls={detailsId} onClick={() => setExpanded(value => !value)} />}
    </div>
    {advanced && <div id={detailsId} data-region="advanced-conditions" hidden={!expanded}
      style={{ display: expanded ? 'flex' : 'none', alignItems: 'end', flexWrap: 'wrap', gap: 12, paddingTop: 8, borderTop: '1px solid #eee' }}>{advanced}</div>}
  </div>;
}

import { useEffect, useState } from 'react';
import { ScreenTitle } from '../ScreenTitle';
import { AsyncFeedback } from '../AsyncFeedback';
import { Button } from '../ui';
import { RecordGrid, type GridColumn } from '../RecordGrid';
import { apiFetch } from '../auth/sessionClient';
import { showAmount, showDate, showNumber } from '../format';
import { ledgerWords, type EntityDefinition } from './definitions';

type Row = Record<string, string> & { key: string };
type View = 'balance' | 'lots' | 'moves';
const text = (value: unknown) => (value === null || value === undefined ? '' : String(value));

/**
 * The quantity ledger as it stands: what there is per thing and place, with its value (each lot at its own cost),
 * the lots behind it (oldest first - the order they are taken out in), and every movement with the lot it touched and its cost.
 * Quantities are moved by the screens whose definition has a "ledger" part; nothing is typed here.
 * A screen made from a definition {"ledgerView": {"show": "all" | "balance" | "lots" | "moves"}}: one view, or the three as tabs.
 */
export function LedgerViewScreen({ entity }: { entity: EntityDefinition }) {
  const show = entity.definition.ledgerView?.show ?? 'all', title = entity.definition.title;
  const of = entity.definition.ledgerView?.thing ?? null;           // only this thing's quantities (none: the whole ledger)
  const { thing, place, lot } = ledgerWords(of);
  const [view, setView] = useState<View>(show === 'all' ? 'balance' : show);
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState('');
  const [chosen, setChosen] = useState<{ thingId: string; placeId: string; label: string } | null>(null);
  async function load(next: View, picked = chosen) {
    setError('');
    const query = new URLSearchParams({ ...(picked && next !== 'balance' ? { thing: picked.thingId, place: picked.placeId } : {}), ...(of ? { entity: of } : {}) }).toString();
    const response = await apiFetch(`/api/ledger/${next}${query ? `?${query}` : ''}`);
    if (!response.ok) { setError('수량을 읽지 못했습니다.'); return; }
    const list = await response.json() as Record<string, unknown>[];
    setRows(list.map((item, index) => ({ key: String(index), ...Object.fromEntries(Object.entries(item).map(([name, value]) => [name, text(value)])) })));
  }
  useEffect(() => { void load(view).catch(() => setError('수량을 읽지 못했습니다.')); }, [view, chosen]);   // eslint-disable-line react-hooks/exhaustive-deps
  const number = (name: string) => (row: Row) => showNumber(row[name]);
  const money = (name: string) => (row: Row) => showAmount(Number(row[name] || 0));
  const columns: Record<View, GridColumn<Row>[]> = {
    balance: [{ key: 'thing', label: thing }, { key: 'place', label: place, width: 180 }, { key: 'quantity', label: '현재 수량', width: 110, align: 'right', render: number('quantity') },
      { key: 'amount', label: '금액', width: 130, align: 'right', render: money('amount') }, { key: 'lots', label: `${lot} 수`, width: 80, align: 'right' }, { key: 'tracking', label: `${lot} 관리`, width: 100, align: 'center', render: row => (row.tracking === 'LOT' ? 'LOT 관리' : '수량만') }],
    lots: [{ key: 'lot', label: lot, width: 160, align: 'center' }, { key: 'thing', label: thing }, { key: 'place', label: place, width: 160 },
      { key: 'receivedOn', label: '들어온 날', width: 100, align: 'center', render: row => showDate(row.receivedOn) }, { key: 'unitCost', label: '단가', width: 100, align: 'right', render: money('unitCost') },
      { key: 'received', label: '들어온 수량', width: 100, align: 'right', render: number('received') }, { key: 'remaining', label: '남은 수량', width: 100, align: 'right', render: number('remaining') },
      { key: 'amount', label: '남은 금액', width: 120, align: 'right', render: money('amount') }, { key: 'source', label: '들어온 화면', width: 160 }],
    moves: [{ key: 'movedOn', label: '일자', width: 100, align: 'center', render: row => showDate(row.movedOn) }, { key: 'direction', label: '구분', width: 70, align: 'center', render: row => (row.direction === 'IN' ? '들어옴' : '나감') },
      { key: 'thing', label: thing }, { key: 'place', label: place, width: 150 }, { key: 'lot', label: lot, width: 160, align: 'center' },
      { key: 'quantity', label: '수량', width: 90, align: 'right', render: number('quantity') }, { key: 'unitCost', label: '단가', width: 100, align: 'right', render: money('unitCost') },
      { key: 'amount', label: '금액(원가)', width: 120, align: 'right', render: money('amount') }, { key: 'source', label: '화면', width: 150 }, { key: 'by', label: '처리자', width: 90 }],
  };
  return <div data-ui="ledger" style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minHeight: 0 }}>
    <ScreenTitle>{title}</ScreenTitle>
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }} role="group" aria-label="보기">
      {([['balance', '현재 수량'], ['lots', lot], ['moves', '들고 난 내역']] as [View, string][]).filter(([id]) => show === 'all' || id === show).map(([id, label]) =>
        <Button key={id} label={label} data-view={id} aria-pressed={view === id} outlined={view !== id} variant={view === id ? 'primary' : undefined} onClick={() => setView(id)} />)}
      {chosen && view !== 'balance' && <span style={{ fontSize: 13 }}>{chosen.label} <Button label="전체 보기" variant="ghost" onClick={() => setChosen(null)} /></span>}
      <span style={{ flex: 1 }} />
      <Button label="새로 고침" icon="refresh" outlined onClick={() => void load(view)} />
    </div>
    <AsyncFeedback error={error} />
    <RecordGrid label={`${title} ${view}`} rows={rows} columns={columns[view]} keyField="key" total={rows.length}
      onSelect={row => { if (view === 'balance' && show === 'all') { setChosen({ thingId: row.thingId, placeId: row.placeId, label: `${row.thing} · ${row.place}` }); setView('lots'); } }} />
  </div>;
}

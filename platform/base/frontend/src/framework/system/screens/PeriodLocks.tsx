import { useEffect, useState } from 'react';
import { ScreenTitle } from '../../ScreenTitle';
import { AsyncFeedback } from '../../AsyncFeedback';
import { AlertDialog, Button } from '../../ui';
import { formatDateTime, showNumber } from '../../format';
import { adminApi } from '../adminApi';
import { definitionOf, ledgerWords } from '../../app/definitions';
import './admin.css';

export const meta = { code: 'SYS0014', title: '마감', icon: 'lock', system: false, apis: ['/api/locks', '/api/ledger/month-end'], keywords: ['마감', '월 마감', '기간 마감', '잠금'] };

type Month = { period: string; closed: boolean; records: number; closedBy: string | null; closedAt: string | null };
type Group = { group: string; screens: string[]; keys: string[]; through: string | null; months: Month[] };
type Balance = { thing: string; place: string; quantity: number; amount: number; lots: number };
const said = (period: string) => `${period.slice(0, 4)}년 ${Number(period.slice(5, 7))}월`;
const next = (period: string) => { const [year, month] = period.split('-').map(Number); return month === 12 ? `${year + 1}-01` : `${year}-${String(month + 1).padStart(2, '0')}`; };

/**
 * Month closing, one page per group of work that is closed together. A closed month takes no registration, change, deletion or status
 * action of that group's records dated in it. Months close in order; only the newest closed month opens again. A group whose screens
 * move quantities also keeps what was held at the end of each closed month.
 */
export default function PeriodLocks() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [chosen, setChosen] = useState('');
  const [shown, setShown] = useState<string | null>(null);
  const [balances, setBalances] = useState<Balance[]>([]);
  const [asking, setAsking] = useState<{ period: string; open: boolean } | null>(null);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { void adminApi<Group[]>('/api/locks').then(list => { setGroups(list); setChosen(current => current || list[0]?.group || ''); }).catch(cause => setError(cause.message)).finally(() => setLoaded(true)); }, []);
  const group = groups.find(item => item.group === chosen);
  const keepsLedger = Boolean(group?.keys.some(key => definitionOf(key)?.ledger));      // a group of screens that move the quantity ledger: its month-end is kept
  useEffect(() => {
    if (!shown || !keepsLedger || !group) { setBalances([]); return; }
    void adminApi<Balance[]>(`/api/ledger/month-end/${encodeURIComponent(group.group)}/${shown}`).then(setBalances).catch(cause => setError(cause.message));
  }, [shown, group?.group]);  // eslint-disable-line react-hooks/exhaustive-deps
  const closable = group?.through ? next(group.through) : null;
  async function run(period: string, open: boolean) {
    if (!group) return;
    setError(''); setDone(''); setAsking(null);
    const path = `/api/locks/${encodeURIComponent(group.group)}`;
    try {
      setGroups(open ? await adminApi<Group[]>(`${path}/${period}`, 'DELETE') : await adminApi<Group[]>(path, 'POST', { period }));
      setDone(`${group.group} ${said(period)}${open ? '을 다시 열었습니다.' : '을 마감했습니다.'}`);
      setShown(open ? null : period);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '처리하지 못했습니다.'); }
  }
  return <div className="sys-page is-flow" data-ui="period-locks">
    <div className="sys-head"><ScreenTitle>마감</ScreenTitle>
      {group && <span className="sys-muted">{group.through ? `${group.group}: ${said(group.through)}까지 마감됨` : `${group.group}: 마감한 달이 없습니다`}</span>}</div>
    <AsyncFeedback error={error} succeeded={Boolean(done)} successText={done} />
    {loaded && groups.length === 0 && <p className="sys-muted">마감하는 업무가 아직 없습니다.</p>}
    {groups.length > 1 && <div role="group" aria-label="마감 묶음" style={{ display: 'flex', gap: 6 }}>
      {groups.map(item => <Button key={item.group} label={item.group} aria-pressed={item.group === chosen} outlined={item.group !== chosen} variant={item.group === chosen ? 'primary' : undefined}
        onClick={() => { setChosen(item.group); setShown(null); }} />)}</div>}
    {group && <>
      <p className="sys-muted" style={{ margin: '0 0 8px' }}>마감한 달의 {group.screens.join(', ')} 자료는 등록·수정·삭제·상태 처리를 할 수 없습니다. 달 순서대로 마감하고, 다시 열기는 가장 최근에 마감한 달만 됩니다.</p>
      <table className="bp6-html-table bp6-compact bp6-html-table-bordered" style={{ width: '100%', maxWidth: 900 }} aria-label={`${group.group} 달별 마감`}>
        <thead><tr><th style={{ width: 130, textAlign: 'center' }}>달</th><th style={{ width: 80, textAlign: 'center' }}>상태</th><th style={{ width: 90, textAlign: 'right' }}>자료 건수</th>
          <th style={{ width: 110 }}>마감한 사람</th><th style={{ width: 170, textAlign: 'center' }}>마감 일시</th><th /></tr></thead>
        <tbody>{group.months.map(month => {
          const canClose = !month.closed && (closable ? month.period === closable : true);
          const canOpen = month.closed && month.period === group.through;
          return <tr key={month.period} data-period={month.period}>
            <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>{month.period.replace('-', '/')}{month.period === group.months[0]?.period ? ' (이번 달)' : ''}</td>
            <td style={{ textAlign: 'center' }}>{month.closed ? <span className="fw-status is-done">마감</span> : <span className="fw-status is-start">열림</span>}</td>
            <td style={{ textAlign: 'right' }}>{showNumber(month.records)}</td>
            <td>{month.closedBy ?? ''}</td><td style={{ textAlign: 'center' }}>{month.closedAt ? formatDateTime(month.closedAt) : ''}</td>
            <td style={{ whiteSpace: 'nowrap' }}>
              {month.closed && keepsLedger && <Button label={`${month.period} 기말 수량`} size="sm" variant="ghost" icon="th" onClick={() => setShown(shown === month.period ? null : month.period)} />}
              {canOpen && <Button label={`${month.period} 다시 열기`} size="sm" onClick={() => setAsking({ period: month.period, open: true })} />}
              {canClose && <Button label={`${month.period} 마감`} size="sm" variant="primary" outlined onClick={() => setAsking({ period: month.period, open: false })} />}
            </td>
          </tr>; })}</tbody>
      </table>
      {shown && keepsLedger && <section style={{ marginTop: 16 }} aria-label={`${said(shown)} 기말 수량`}>
        <h3 style={{ margin: '0 0 6px', fontSize: 14 }}>{said(shown)} 기말 수량</h3>
        <table className="bp6-html-table bp6-compact bp6-html-table-striped" style={{ width: '100%', maxWidth: 900 }}>
          <thead><tr><th>{ledgerWords().thing}</th><th>{ledgerWords().place}</th><th style={{ width: 120, textAlign: 'right' }}>수량</th><th style={{ width: 140, textAlign: 'right' }}>금액</th><th style={{ width: 80, textAlign: 'right' }}>묶음 수</th></tr></thead>
          <tbody>{balances.map((row, index) => <tr key={index}><td>{row.thing}</td><td>{row.place}</td>
            <td style={{ textAlign: 'right' }}>{showNumber(row.quantity)}</td><td style={{ textAlign: 'right' }}>{showNumber(row.amount)}</td><td style={{ textAlign: 'right' }}>{showNumber(row.lots)}</td></tr>)}
            {balances.length === 0 && <tr><td colSpan={5} className="sys-muted">그 달 말에 남은 수량이 없습니다.</td></tr>}</tbody>
        </table>
      </section>}
    </>}
    <AlertDialog isOpen={Boolean(asking)} onOpenChange={open => { if (!open) setAsking(null); }} title={asking?.open ? '다시 열기' : '마감'}
      cancelLabel="취소" actionLabel={asking?.open ? '다시 열기' : '마감'} onAction={() => { if (asking) void run(asking.period, asking.open); }}
      description={!asking || !group ? '' : asking.open ? `${group.group} ${said(asking.period)}을 다시 열면 그 달 자료를 다시 고칠 수 있습니다.`
        : `${group.group} ${said(asking.period)}${group.through ? '' : '과 그 이전 달'}을 마감합니다. 그 달 자료는 더 고칠 수 없습니다.`} />
  </div>;
}

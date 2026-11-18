import { useEffect, useState } from 'react';
import { ScreenTitle } from '../../ScreenTitle';
import { AsyncFeedback } from '../../AsyncFeedback';
import { Button, Checkbox, Select } from '../../ui';
import { adminApi } from '../adminApi';
import './admin.css';

export const meta = { code: 'SYS0005', title: '프로그램 권한 편성', icon: 'settings', keywords: ['프로그램 권한', '조회', '저장', '삭제', '버튼 권한'] };

type Role = { roleCode: string; roleName: string };
type Grant = { programCode: string; programName: string; query: boolean; create: boolean; save: boolean; delete: boolean; print: boolean; inMenu: boolean };
const ACTIONS = [['query', '조회'], ['create', '신규'], ['save', '저장'], ['delete', '삭제'], ['print', '출력']] as const;

/** What a role may do inside each program: 조회/신규/저장/삭제/출력. The toolbar and the API both follow it. */
export default function ProgramPermission() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [role, setRole] = useState('');
  const [rows, setRows] = useState<Grant[]>([]);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const fail = (cause: unknown) => setError(cause instanceof Error ? cause.message : '처리하지 못했습니다.');
  async function pick(code: string) { setRole(code); setSaved(false); setRows(code ? await adminApi<Grant[]>(`/api/system/roles/${code}/programs`) : []); }
  useEffect(() => { void (async () => {
    const list = (await adminApi<Role[]>('/api/system/roles')).filter(item => item.roleCode !== 'ADMIN');
    setRoles(list);
    if (list[0]) await pick(list[0].roleCode);
  })().catch(fail); }, []);
  const set = (code: string, changes: Partial<Grant>) => { setSaved(false); setRows(previous => previous.map(row => row.programCode === code ? { ...row, ...changes } : row)); };
  const all = (row: Grant) => ACTIONS.every(([key]) => row[key]);
  return <div className="sys-page" data-ui="program-permission">
    <div className="sys-head"><ScreenTitle>프로그램 권한 편성</ScreenTitle>
      <div className="sys-actions">
        <div style={{ width: 220 }}><Select label="역할" hideLabel value={role} onChange={value => void pick(value).catch(fail)}
          options={roles.length ? roles.map(item => ({ value: item.roleCode, label: `${item.roleName} (${item.roleCode})` })) : [{ value: '', label: '역할이 없습니다' }]} /></div>
        <Button label="저장" variant="primary" size="sm" isDisabled={!role}
          onClick={() => { setError(''); void adminApi(`/api/system/roles/${role}/programs`, 'PUT', { programs: rows }).then(() => setSaved(true)).catch(fail); }} />
      </div></div>
    <AsyncFeedback error={error} succeeded={saved} successText="저장되었습니다." />
    <section className="sys-card bp6-card" aria-label="프로그램 권한" style={{ flex: 1, padding: 0 }}>
      <table className="sys-table bp6-html-table bp6-html-table-striped bp6-compact">
        <thead><tr><th>프로그램</th><th>메뉴 권한</th><th>전체</th>{ACTIONS.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.programCode}>
          <td>{row.programName} <span className="sys-muted">{row.programCode}</span></td>
          <td className="sys-muted">{row.inMenu ? '있음' : '없음'}</td>
          <td><Checkbox label={`${row.programName} 전체`} hideLabel checked={all(row)} indeterminate={!all(row) && ACTIONS.some(([key]) => row[key])}
            onChange={on => set(row.programCode, { query: on, create: on, save: on, delete: on, print: on })} /></td>
          {ACTIONS.map(([key, label]) => <td key={key}><Checkbox label={`${row.programName} ${label}`} hideLabel checked={row[key]} onChange={on => set(row.programCode, { [key]: on })} /></td>)}
        </tr>)}</tbody>
      </table>
    </section>
  </div>;
}

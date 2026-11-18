import { useEffect, useState } from 'react';
import { BusinessWorkspace } from '../../BusinessWorkspace';
import { QueryPanel } from '../../QueryPanel';
import { RecordGrid, type GridColumn } from '../../RecordGrid';
import type { FieldDefinition, FieldValues } from '../../fields';
import type { EditableRecord } from '../../RecordEditor';
import { Button, Checkbox, Select, TextInput } from '../../ui';
import { formatDateTime } from '../../format';
import { adminApi } from '../adminApi';

export const meta = { code: 'SYS0001', title: '사용자 관리', icon: 'users', keywords: ['사용자', '계정', '회원', '가입 승인', '승인', '비밀번호'] };

type User = { username: string; displayName: string; email: string; status: string; requestedAt: string; approvedBy: string; roles: string };
type Role = { roleCode: string; roleName: string; enabled: boolean };
const STATUS: Record<string, string> = { PENDING: '승인 대기', ACTIVE: '사용', REJECTED: '반려', LOCKED: '잠금' };
const columns: GridColumn<User & { state: string }>[] = [
  { key: 'username', label: '아이디', width: 150 }, { key: 'displayName', label: '이름', width: 150 }, { key: 'email', label: '이메일' },
  { key: 'state', label: '상태', width: 110, align: 'center' }, { key: 'roles', label: '역할', width: 200 }, { key: 'requestedAt', label: '가입 신청', width: 170, align: 'center' },
];

export default function UserManagement() {
  const [rows, setRows] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [filter, setFilter] = useState<FieldValues>({});
  const [selected, setSelected] = useState<EditableRecord | null>(null);
  const [password, setPassword] = useState('');
  const [notice, setNotice] = useState('');
  const load = async (values: FieldValues = filter) => {
    setFilter(values);
    setRows(await adminApi<User[]>('/api/system/users'));
    setRoles(await adminApi<Role[]>('/api/system/roles'));
  };
  useEffect(() => { void load().catch(() => {}); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  const shown = rows.filter(row => (!filter.keyword || `${row.username} ${row.displayName} ${row.email}`.toLowerCase().includes(filter.keyword.toLowerCase()))
    && (!filter.status || row.status === filter.status));
  const fields: FieldDefinition[] = [
    { name: 'displayName', label: '이름', required: true },
    { name: 'email', label: '이메일', type: 'email' },
    { name: 'status', label: '상태', render: control => <Select label="상태" value={control.value || 'ACTIVE'} isDisabled={control.disabled} onChange={control.onChange}
        options={Object.entries(STATUS).map(([value, label]) => ({ value, label }))} /> },
    { name: 'roles', label: '역할', group: 'extra', render: control => {
        const picked = new Set(control.value.split(',').filter(Boolean));
        return <div><div style={{ fontSize: 13, marginBottom: 6 }}>역할</div><div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {roles.filter(role => role.enabled || picked.has(role.roleCode)).map(role => <Checkbox key={role.roleCode} label={`${role.roleName} (${role.roleCode})`} checked={picked.has(role.roleCode)}
            isDisabled={control.disabled} onChange={checked => { const next = new Set(picked); if (checked) next.add(role.roleCode); else next.delete(role.roleCode); control.onChange([...next].sort().join(',')); }} />)}
        </div></div>;
      } },
  ];
  async function save(values: FieldValues, id: string | number | null) {
    if (id === null) throw new Error('새 계정은 로그인 화면의 회원가입으로 신청합니다. 목록에서 사용자를 선택하세요.');
    await adminApi(`/api/system/users/${id}`, 'PUT', { displayName: values.displayName, email: values.email, status: values.status || 'ACTIVE', roles: values.roles.split(',').filter(Boolean) });
    await load();
  }
  async function decide(status: 'ACTIVE' | 'REJECTED') {
    if (!selected) return;
    const user = rows.find(row => row.username === selected.id);
    if (!user) return;
    const current = user.roles.split(',').filter(Boolean);
    await adminApi(`/api/system/users/${user.username}`, 'PUT', { displayName: user.displayName, email: user.email, status, roles: status === 'ACTIVE' && current.length === 0 ? ['USER'] : current });
    setNotice(status === 'ACTIVE' ? `${user.displayName} 님의 가입을 승인했습니다.` : `${user.displayName} 님의 가입을 반려했습니다.`);
    setSelected(null);
    await load();
  }
  const pending = selected && rows.find(row => row.username === selected.id)?.status === 'PENDING';
  return <BusinessWorkspace title="사용자 관리"
    actions={{ query: { form: 'user-query' }, save: { form: 'user-editor', disabled: !selected } }}
    query={<QueryPanel formId="user-query" onQuery={load} fields={[{ name: 'keyword', label: '아이디·이름·이메일' },
      { name: 'status', label: '상태', render: control => <Select label="상태" value={control.value} onChange={control.onChange}
          options={[{ value: '', label: '전체' }, ...Object.entries(STATUS).map(([value, label]) => ({ value, label }))]} /> }]} />}
    results={<RecordGrid rows={shown.map(row => ({ ...row, state: STATUS[row.status] ?? row.status, requestedAt: formatDateTime(row.requestedAt) }))} columns={columns} keyField="username"
      onSelect={row => { setNotice(''); setPassword(''); setSelected({ id: row.username, values: { displayName: row.displayName, email: row.email, status: row.status, roles: row.roles } }); }} />}
    editor={{ fields, record: selected, onSave: save, onNew: () => setSelected(null), formId: 'user-editor',
      children: () => selected ? <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        {pending && <><Button type="button" label="가입 승인" variant="primary" onClick={() => void decide('ACTIVE')} />
          <Button type="button" label="반려" variant="destructive" outlined onClick={() => void decide('REJECTED')} /></>}
        <div style={{ width: 220 }}><TextInput label="새 비밀번호 (8자 이상)" type="password" value={password} onChange={setPassword} /></div>
        <Button type="button" label="비밀번호 초기화" isDisabled={password.length < 8} onClick={() => void adminApi(`/api/system/users/${selected.id}/password`, 'POST', { password })
          .then(() => { setPassword(''); setNotice('비밀번호를 바꿨습니다.'); }).catch(error => setNotice(error instanceof Error ? error.message : '실패'))} />
        {notice && <span role="status" style={{ fontSize: 13 }}>{notice}</span>}
      </div> : notice ? <div role="status" style={{ gridColumn: '1 / -1', fontSize: 13 }}>{notice}</div> : null }} />;
}

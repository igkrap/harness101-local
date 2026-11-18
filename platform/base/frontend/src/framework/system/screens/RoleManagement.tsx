import { useState } from 'react';
import { BusinessWorkspace } from '../../BusinessWorkspace';
import { RecordGrid, type GridColumn } from '../../RecordGrid';
import type { FieldDefinition, FieldValues } from '../../fields';
import type { EditableRecord } from '../../RecordEditor';
import { Select } from '../../ui';
import { adminApi } from '../adminApi';

export const meta = { code: 'SYS0002', title: '역할 관리', icon: 'users', keywords: ['역할', '권한', 'role', '롤'] };

type Role = { roleCode: string; roleName: string; description: string; enabled: boolean; users: number };
const columns: GridColumn<Role & { state: string }>[] = [
  { key: 'roleCode', label: '역할 코드', width: 160 }, { key: 'roleName', label: '역할 이름', width: 200 },
  { key: 'description', label: '설명' }, { key: 'users', label: '사용자 수', width: 100, align: 'right' }, { key: 'state', label: '사용', width: 90, align: 'center' },
];
const fields: FieldDefinition[] = [
  { name: 'roleCode', label: '역할 코드', required: true, placeholder: '예: SALES (등록 후 변경 불가)' },
  { name: 'roleName', label: '역할 이름', required: true },
  { name: 'description', label: '설명' },
  { name: 'enabled', label: '사용', render: control => <Select label="사용" value={control.value || 'Y'} isDisabled={control.disabled} onChange={control.onChange}
      options={[{ value: 'Y', label: '사용' }, { value: 'N', label: '사용 안 함' }]} /> },
];

export default function RoleManagement() {
  const [rows, setRows] = useState<Role[]>([]);
  const [selected, setSelected] = useState<EditableRecord | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const load = async () => setRows(await adminApi<Role[]>('/api/system/roles'));
  async function save(values: FieldValues, id: string | number | null) {
    const body = { roleCode: values.roleCode, roleName: values.roleName, description: values.description, enabled: values.enabled !== 'N' };
    if (id === null) await adminApi('/api/system/roles', 'POST', body);
    else await adminApi(`/api/system/roles/${id}`, 'PUT', body);
    await load();
  }
  return <BusinessWorkspace title="역할 관리"
    actions={{ query: { onClick: load }, create: { onClick: () => { setSelected(null); setResetKey(key => key + 1); } }, save: { form: 'role-editor' },
      remove: { disabled: !selected, confirm: '선택한 역할을 삭제할까요?', onClick: async () => { if (selected) { await adminApi(`/api/system/roles/${selected.id}`, 'DELETE'); setSelected(null); await load(); } } } }}
    query={<div />}
    results={<RecordGrid rows={rows.map(row => ({ ...row, state: row.enabled ? '사용' : '중지' }))} columns={columns} keyField="roleCode"
      onSelect={row => setSelected({ id: row.roleCode, values: { roleCode: row.roleCode, roleName: row.roleName, description: row.description, enabled: row.enabled ? 'Y' : 'N' } })} />}
    editor={{ fields, record: selected, onSave: save, onNew: () => setSelected(null), resetKey, formId: 'role-editor' }} />;
}

import { useEffect, useState } from 'react';
import { ScreenTitle } from '../../ScreenTitle';
import { AsyncFeedback } from '../../AsyncFeedback';
import { RecordGrid, type GridColumn } from '../../RecordGrid';
import { AlertDialog, Button, Select, TextInput, Tree } from '../../ui';
import { adminApi } from '../adminApi';
import { refreshCommonCodes } from '../commonCodes';
import './admin.css';

export const meta = { code: 'SYS0007', title: '공통 코드 관리', icon: 'list', keywords: ['공통코드', '코드', '선택값', '콤보', '드롭다운', '구분값'] };

type Group = { groupCode: string; groupName: string; description: string; enabled: boolean; codes: number };
type Code = { code: string; codeName: string; sortOrder: number; enabled: boolean };
const YES_NO = [{ value: 'Y', label: '사용' }, { value: 'N', label: '사용 안 함' }];
const columns: GridColumn<Code & { state: string }>[] = [
  { key: 'code', label: '코드', width: 140, align: 'center' }, { key: 'codeName', label: '코드 이름' }, { key: 'sortOrder', label: '순서', width: 80, align: 'right' }, { key: 'state', label: '사용', width: 100, align: 'center' },
];
const emptyGroup = { groupCode: '', groupName: '', description: '', enabled: 'Y' }, emptyCode = { code: '', codeName: '', sortOrder: '', enabled: 'Y' };

/** Groups of codes (left) and the codes of the chosen group (right). Screens use them as drop-down values. */
export default function CommonCodes() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [current, setCurrent] = useState('');
  const [codes, setCodes] = useState<Code[]>([]);
  const [group, setGroup] = useState(emptyGroup);
  const [code, setCode] = useState(emptyCode);
  const [editingGroup, setEditingGroup] = useState(false);
  const [editingCode, setEditingCode] = useState('');
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<'group' | 'code' | null>(null);
  const run = (work: () => Promise<void>) => { setError(''); void work().catch(cause => setError(cause instanceof Error ? cause.message : '처리하지 못했습니다.')); };
  async function pick(groupCode: string, list = groups) {
    setCurrent(groupCode); setEditingCode(''); setCode(emptyCode);
    const chosen = list.find(item => item.groupCode === groupCode);
    setEditingGroup(Boolean(chosen));
    setGroup(chosen ? { groupCode: chosen.groupCode, groupName: chosen.groupName, description: chosen.description, enabled: chosen.enabled ? 'Y' : 'N' } : emptyGroup);
    setCodes(groupCode ? await adminApi<Code[]>(`/api/system/code-groups/${groupCode}/codes`) : []);
  }
  async function load(keep = current) {
    const list = await adminApi<Group[]>('/api/system/code-groups');
    setGroups(list);
    await pick(list.some(item => item.groupCode === keep) ? keep : list[0]?.groupCode ?? '', list);
  }
  useEffect(() => { run(() => load()); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  async function saveGroup() {
    const body = { groupCode: group.groupCode, groupName: group.groupName, description: group.description, enabled: group.enabled !== 'N' };
    if (editingGroup) await adminApi(`/api/system/code-groups/${current}`, 'PUT', body); else await adminApi('/api/system/code-groups', 'POST', body);
    refreshCommonCodes();
    await load(editingGroup ? current : group.groupCode.trim().toUpperCase());
  }
  async function saveCode() {
    const body = { code: code.code, codeName: code.codeName, sortOrder: Number(code.sortOrder) || 0, enabled: code.enabled !== 'N' };
    const list = editingCode ? await adminApi<Code[]>(`/api/system/code-groups/${current}/codes/${editingCode}`, 'PUT', body)
      : await adminApi<Code[]>(`/api/system/code-groups/${current}/codes`, 'POST', body);
    refreshCommonCodes(current);
    setCodes(list); setEditingCode(''); setCode(emptyCode);
    setGroups(await adminApi<Group[]>('/api/system/code-groups'));
  }
  return <div className="sys-page" data-ui="common-codes">
    <div className="sys-head"><ScreenTitle>공통 코드 관리</ScreenTitle><Button label="새로고침" onClick={() => run(() => load())} /></div>
    <AsyncFeedback error={error} />
    <div className="sys-columns">
      <section className="sys-card bp6-card" aria-label="코드 그룹">
        <h3>코드 그룹</h3>
        <Tree<Group> onToggle={() => undefined} onClick={node => { const item = node.nodeData; if (item) run(() => pick(item.groupCode)); }}
          nodes={groups.map(item => ({ id: item.groupCode, nodeData: item, isSelected: item.groupCode === current, label: `${item.groupName}${item.enabled ? '' : ' (사용 안 함)'}`,
            secondaryLabel: <span className="sys-muted">{item.groupCode} · {item.codes}개</span> }))} />
        {groups.length === 0 && <div className="sys-muted">아직 코드 그룹이 없습니다.</div>}
        <h3>{editingGroup ? '그룹 수정' : '그룹 추가'}</h3>
        <div className="sys-form">
          <TextInput label="그룹 코드" placeholder="예: UNIT" value={group.groupCode} isDisabled={editingGroup} onChange={value => setGroup(previous => ({ ...previous, groupCode: value }))} />
          <TextInput label="그룹 이름" placeholder="예: 단위" value={group.groupName} onChange={value => setGroup(previous => ({ ...previous, groupName: value }))} />
          <TextInput label="설명" value={group.description} onChange={value => setGroup(previous => ({ ...previous, description: value }))} />
          {editingGroup && <Select label="사용" value={group.enabled} onChange={value => setGroup(previous => ({ ...previous, enabled: value }))} options={YES_NO} />}
        </div>
        <div className="sys-actions">
          <Button label={editingGroup ? '그룹 저장' : '그룹 추가'} variant="primary" isDisabled={!group.groupCode.trim() || !group.groupName.trim()} onClick={() => run(saveGroup)} />
          {editingGroup && <Button label="새 그룹 입력" onClick={() => { setEditingGroup(false); setGroup(emptyGroup); }} />}
          {editingGroup && <Button label="그룹 삭제" variant="destructive" outlined onClick={() => setConfirm('group')} />}
        </div>
      </section>
      <section className="sys-card bp6-card" aria-label="코드">
        <h3>{current ? `${groups.find(item => item.groupCode === current)?.groupName ?? current} 코드` : '코드'}</h3>
        <RecordGrid label="코드" rows={codes.map(item => ({ ...item, state: item.enabled ? '사용' : '사용 안 함' }))} columns={columns} keyField="code"
          onSelect={row => { setEditingCode(row.code); setCode({ code: row.code, codeName: row.codeName, sortOrder: String(row.sortOrder), enabled: row.enabled ? 'Y' : 'N' }); }} />
        <h3>{editingCode ? '코드 수정' : '코드 추가'}</h3>
        <div className="sys-form">
          <TextInput label="코드 (저장되는 값)" placeholder="예: EA" value={code.code} isDisabled={Boolean(editingCode)} onChange={value => setCode(previous => ({ ...previous, code: value }))} />
          <TextInput label="코드 이름 (화면에 보이는 값)" placeholder="예: 개" value={code.codeName} onChange={value => setCode(previous => ({ ...previous, codeName: value }))} />
          <TextInput label="순서" value={code.sortOrder} onChange={value => setCode(previous => ({ ...previous, sortOrder: value.replace(/[^0-9]/g, '') }))} />
          <Select label="사용" value={code.enabled} onChange={value => setCode(previous => ({ ...previous, enabled: value }))} options={YES_NO} />
        </div>
        <div className="sys-actions">
          <Button label={editingCode ? '코드 저장' : '코드 추가'} variant="primary" isDisabled={!current || !code.code.trim() || !code.codeName.trim()} onClick={() => run(saveCode)} />
          {editingCode && <Button label="새 코드 입력" onClick={() => { setEditingCode(''); setCode(emptyCode); }} />}
          {editingCode && <Button label="코드 삭제" variant="destructive" outlined onClick={() => setConfirm('code')} />}
        </div>
        <div className="sys-muted">이미 저장된 자료가 쓰는 코드는 지우기보다 "사용 안 함"으로 두세요. 새 입력에서만 빠지고 기존 자료는 그대로 읽힙니다.</div>
      </section>
    </div>
    <AlertDialog isOpen={confirm !== null} onOpenChange={open => { if (!open) setConfirm(null); }} title={confirm === 'group' ? '그룹 삭제' : '코드 삭제'}
      description={confirm === 'group' ? `${group.groupName} 그룹과 그 안의 코드를 모두 삭제할까요?` : `${code.codeName} 코드를 삭제할까요?`}
      cancelLabel="취소" actionLabel="삭제" actionVariant="destructive"
      onAction={() => { const what = confirm; setConfirm(null); run(async () => {
        if (what === 'group') { await adminApi(`/api/system/code-groups/${current}`, 'DELETE'); refreshCommonCodes(); await load(''); }
        else { setCodes(await adminApi<Code[]>(`/api/system/code-groups/${current}/codes/${editingCode}`, 'DELETE')); refreshCommonCodes(current); setEditingCode(''); setCode(emptyCode); setGroups(await adminApi<Group[]>('/api/system/code-groups')); }
      }); }} />
  </div>;
}

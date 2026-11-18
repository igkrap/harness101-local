import { useEffect, useState } from 'react';
import { ScreenTitle } from '../../ScreenTitle';
import { AsyncFeedback } from '../../AsyncFeedback';
import { AlertDialog, Button, Select, TextInput, Tree, type TreeNode } from '../../ui';
import { MenuIcon } from '../../workspace/menuIcons';
import { IconPicker } from '../IconPicker';
import { loadSession } from '../../auth/sessionClient';
import { adminApi } from '../adminApi';
import './admin.css';

export const meta = { code: 'SYS0003', title: '메뉴 편성', icon: 'list', keywords: ['메뉴', '모듈', '모듈', '메뉴', '폴더', '프로그램 배치'] };

type Module = { moduleCode: string; moduleName: string; icon: string; sortOrder: number; enabled: boolean; menus: number };
type Menu = { menuId: number; moduleCode: string; parentId: number | null; menuType: 'FOLDER' | 'PROGRAM'; programCode: string; menuName: string; sortOrder: number; icon: string };
type Program = { programCode: string; programName: string; moduleName: string };

/** Modules on the left; the chosen module's menu tree (folders and programs) on the right. */
export default function MenuArrangement() {
  const [modules, setModules] = useState<Module[]>([]);
  const [menus, setMenus] = useState<Menu[]>([]);
  const [programs, setPrograms] = useState<Program[]>([]);
  const [moduleCode, setModuleCode] = useState('');
  const [picked, setPicked] = useState<number | null>(null);
  const [moduleForm, setModuleForm] = useState({ moduleCode: '', moduleName: '', icon: 'list', sortOrder: '10' });
  const [editingModule, setEditingModule] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [rename, setRename] = useState('');
  const [program, setProgram] = useState('');
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<{ text: string; run: () => Promise<void> } | null>(null);

  async function load(code = moduleCode) {
    const list = await adminApi<Module[]>('/api/system/modules');
    setModules(list);
    const current = list.some(item => item.moduleCode === code) ? code : list[0]?.moduleCode ?? '';
    setModuleCode(current);
    setMenus(current ? await adminApi<Menu[]>(`/api/system/menus?module=${encodeURIComponent(current)}`) : []);
    setPrograms(await adminApi<Program[]>('/api/system/programs'));
  }
  const run = (action: () => Promise<void>) => { setError(''); void action().then(() => loadSession()).catch(cause => setError(cause instanceof Error ? cause.message : '처리하지 못했습니다.')); };
  useEffect(() => { run(() => load()); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const selected = menus.find(menu => menu.menuId === picked) ?? null;
  const targetFolder = selected ? (selected.menuType === 'FOLDER' ? selected.menuId : selected.parentId) : null;
  const unplaced = programs.filter(item => !item.moduleName);
  const children = (parent: number | null) => menus.filter(menu => menu.parentId === parent).sort((a, b) => a.sortOrder - b.sortOrder || a.menuName.localeCompare(b.menuName, 'ko'));
  const body = (menu: Menu, changes: Partial<Menu>) => ({ moduleCode: menu.moduleCode, parentId: menu.parentId, menuName: menu.menuName, sortOrder: menu.sortOrder, icon: menu.icon, ...changes });
  async function move(menu: Menu, delta: number) {
    const siblings = children(menu.parentId);
    const other = siblings[siblings.indexOf(menu) + delta];
    if (!other) return;
    // Renumber the siblings so the swap always takes effect, even when sort orders were equal.
    const order = siblings.map(item => item.menuId);
    const from = order.indexOf(menu.menuId), to = order.indexOf(other.menuId);
    order.splice(from, 1); order.splice(to, 0, menu.menuId);
    for (const [index, id] of order.entries()) {
      const item = siblings.find(entry => entry.menuId === id)!;
      if (item.sortOrder !== index + 1) await adminApi(`/api/system/menus/${id}`, 'PUT', body(item, { sortOrder: index + 1 }));
    }
    await load();
  }
  const tree = (parent: number | null): TreeNode<Menu>[] => children(parent).map(menu => ({
    id: menu.menuId, nodeData: menu, isSelected: picked === menu.menuId, isExpanded: true, hasCaret: false,
    icon: <span className="bp6-tree-node-icon"><MenuIcon name={menu.icon || (menu.menuType === 'FOLDER' ? 'folder' : 'document')} /></span>,
    label: menu.menuName, secondaryLabel: <span className="sys-muted">{menu.menuType === 'FOLDER' ? '폴더' : menu.programCode}</span>,
    childNodes: menu.menuType === 'FOLDER' ? tree(menu.menuId) : undefined }));
  const currentModule = modules.find(item => item.moduleCode === moduleCode);

  return <div className="sys-page" data-ui="menu-arrangement">
    <div className="sys-head"><ScreenTitle>메뉴 편성</ScreenTitle>
      <Button label="새로고침" size="sm" onClick={() => run(() => load())} /></div>
    <AsyncFeedback error={error} />
    <div className="sys-columns">
      <section className="sys-card bp6-card" aria-label="모듈">
        <h3>모듈</h3>
        <Tree<Module> onToggle={() => undefined} onClick={node => { const item = node.nodeData; if (item) { setPicked(null); setEditingModule(false); run(() => load(item.moduleCode)); } }}
          nodes={modules.map(item => ({ id: item.moduleCode, nodeData: item, isSelected: item.moduleCode === moduleCode,
            icon: <span className="bp6-tree-node-icon"><MenuIcon name={item.icon || 'list'} /></span>, label: item.moduleName,
            secondaryLabel: <span className="sys-muted">{item.moduleCode} · 메뉴 {item.menus}</span> }))} />
        <h3>{editingModule ? '모듈 수정' : '모듈 추가'}</h3>
        <div className="sys-form">
          <TextInput label="모듈 코드" value={moduleForm.moduleCode} isDisabled={editingModule} onChange={value => setModuleForm({ ...moduleForm, moduleCode: value.toUpperCase() })} placeholder="예: SALES" />
          <TextInput label="모듈 이름" value={moduleForm.moduleName} onChange={value => setModuleForm({ ...moduleForm, moduleName: value })} placeholder="예: 영업" />
          <TextInput label="순서" value={moduleForm.sortOrder} onChange={value => setModuleForm({ ...moduleForm, sortOrder: value.replace(/\D/g, '') })} />
        </div>
        <IconPicker label="모듈 아이콘" value={moduleForm.icon === 'list' ? '' : moduleForm.icon} defaultIcon="list" defaultLabel="기본 (목록)"
          onChange={value => setModuleForm({ ...moduleForm, icon: value || 'list' })} />
        <div className="sys-actions">
          <Button label={editingModule ? '모듈 저장' : '모듈 추가'} variant="primary" size="sm" isDisabled={!moduleForm.moduleCode || !moduleForm.moduleName}
            onClick={() => run(async () => {
              const payload = { ...moduleForm, sortOrder: Number(moduleForm.sortOrder || 10), enabled: true };
              if (editingModule) await adminApi(`/api/system/modules/${moduleForm.moduleCode}`, 'PUT', payload); else await adminApi('/api/system/modules', 'POST', payload);
              const code = moduleForm.moduleCode;
              setModuleForm({ moduleCode: '', moduleName: '', icon: 'list', sortOrder: '10' }); setEditingModule(false);
              await load(code);
            })} />
          {currentModule && !editingModule && <Button label="선택 모듈 수정" size="sm" onClick={() => { setEditingModule(true);
            setModuleForm({ moduleCode: currentModule.moduleCode, moduleName: currentModule.moduleName, icon: currentModule.icon || 'list', sortOrder: String(currentModule.sortOrder) }); }} />}
          {editingModule && <Button label="취소" size="sm" onClick={() => { setEditingModule(false); setModuleForm({ moduleCode: '', moduleName: '', icon: 'list', sortOrder: '10' }); }} />}
          {currentModule && currentModule.moduleCode !== 'SYSTEM' && <Button label="선택 모듈 삭제" variant="destructive" outlined size="sm"
            onClick={() => setConfirm({ text: `'${currentModule.moduleName}' 모듈을 삭제할까요?`, run: async () => { await adminApi(`/api/system/modules/${currentModule.moduleCode}`, 'DELETE'); await load(''); } })} />}
        </div>
      </section>
      <section className="sys-card bp6-card" aria-label="메뉴 트리">
        <h3>{currentModule ? `${currentModule.moduleName} 메뉴` : '메뉴'}</h3>
        <div className="sys-actions">
          <div style={{ width: 180 }}><TextInput label="새 폴더 이름" value={folderName} onChange={setFolderName} /></div>
          <Button label={targetFolder ? '선택 폴더 안에 폴더 추가' : '폴더 추가'} size="sm" isDisabled={!folderName.trim() || !moduleCode}
            onClick={() => run(async () => { await adminApi('/api/system/menus', 'POST', { moduleCode, parentId: targetFolder, menuType: 'FOLDER', menuName: folderName.trim() }); setFolderName(''); await load(); })} />
          <div style={{ width: 220 }}><Select label="미편성 프로그램" value={program} onChange={setProgram}
            options={[{ value: '', label: unplaced.length ? '프로그램 선택' : '미편성 프로그램 없음' }, ...unplaced.map(item => ({ value: item.programCode, label: `${item.programName} (${item.programCode})` }))]} /></div>
          <Button label={targetFolder ? '선택 폴더에 배치' : '모듈 바로 아래 배치'} variant="primary" size="sm" isDisabled={!program || !moduleCode}
            onClick={() => run(async () => { await adminApi('/api/system/menus', 'POST', { moduleCode, parentId: targetFolder, menuType: 'PROGRAM', programCode: program }); setProgram(''); await load(); })} />
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }} onClick={event => { if (event.target === event.currentTarget) setPicked(null); }}>
          <Tree<Menu> nodes={tree(null)} onToggle={() => undefined} onClick={node => { if (node.nodeData) { setPicked(node.nodeData.menuId); setRename(node.nodeData.menuName); } }} /></div>
        {menus.length === 0 && <div className="sys-muted">아직 메뉴가 없습니다. 폴더를 만들거나 미편성 프로그램을 배치하세요.</div>}
        {selected && <div className="sys-actions" style={{ borderTop: '1px solid var(--fw-border)', paddingTop: 10 }}>
          <div style={{ width: 200 }}><TextInput label="선택한 메뉴 이름" value={rename} onChange={setRename} /></div>
          <Button label="이름 변경" size="sm" isDisabled={!rename.trim() || rename === selected.menuName}
            onClick={() => run(async () => { await adminApi(`/api/system/menus/${selected.menuId}`, 'PUT', body(selected, { menuName: rename.trim() })); await load(); })} />
          <IconPicker label="아이콘" value={selected.icon} defaultIcon={selected.menuType === 'FOLDER' ? 'folder' : 'document'}
            defaultLabel={selected.menuType === 'FOLDER' ? '기본 (폴더)' : '기본 (화면 아이콘)'}
            onChange={value => run(async () => { await adminApi(`/api/system/menus/${selected.menuId}`, 'PUT', body(selected, { icon: value })); await load(); })} />
          <Button label="위로" size="sm" onClick={() => run(() => move(selected, -1))} />
          <Button label="아래로" size="sm" onClick={() => run(() => move(selected, 1))} />
          {selected.parentId !== null && <Button label="폴더 밖으로" size="sm"
            onClick={() => run(async () => { const parent = menus.find(menu => menu.menuId === selected.parentId); await adminApi(`/api/system/menus/${selected.menuId}`, 'PUT', body(selected, { parentId: parent?.parentId ?? null })); await load(); })} />}
          <Select label="다른 모듈로 이동" value="" onChange={value => { if (value) run(async () => { await adminApi(`/api/system/menus/${selected.menuId}`, 'PUT', body(selected, { moduleCode: value, parentId: null })); setPicked(null); await load(); }); }}
            options={[{ value: '', label: '모듈 선택' }, ...modules.filter(item => item.moduleCode !== moduleCode).map(item => ({ value: item.moduleCode, label: item.moduleName }))]} />
          <Button label={selected.menuType === 'FOLDER' ? '폴더 삭제' : '메뉴에서 빼기'} variant="destructive" outlined size="sm"
            onClick={() => setConfirm({ text: selected.menuType === 'FOLDER' ? `'${selected.menuName}' 폴더와 그 안의 배치를 삭제할까요? 프로그램은 미편성으로 돌아갑니다.` : `'${selected.menuName}'을(를) 메뉴에서 뺄까요? 프로그램은 미편성으로 돌아갑니다.`,
              run: async () => { await adminApi(`/api/system/menus/${selected.menuId}`, 'DELETE'); setPicked(null); await load(); } })} />
        </div>}
      </section>
    </div>
    <AlertDialog isOpen={Boolean(confirm)} onOpenChange={open => { if (!open) setConfirm(null); }} title="확인" description={confirm?.text ?? ''} cancelLabel="취소" actionLabel="삭제"
      actionVariant="destructive" onAction={() => { const action = confirm; setConfirm(null); if (action) run(action.run); }} />
  </div>;
}

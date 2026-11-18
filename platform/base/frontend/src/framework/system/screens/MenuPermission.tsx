import { useEffect, useState } from 'react';
import { ScreenTitle } from '../../ScreenTitle';
import { AsyncFeedback } from '../../AsyncFeedback';
import { Button, Checkbox, Select, Tree, type TreeNode } from '../../ui';
import { MenuIcon } from '../../workspace/menuIcons';
import { adminApi } from '../adminApi';
import './admin.css';

export const meta = { code: 'SYS0004', title: '메뉴 권한 편성', icon: 'list', keywords: ['메뉴 권한', '역할', '권한', '접근'] };

type Role = { roleCode: string; roleName: string };
type Module = { moduleCode: string; moduleName: string };
type Menu = { menuId: number; moduleCode: string; parentId: number | null; menuType: 'FOLDER' | 'PROGRAM'; programCode: string; menuName: string; sortOrder: number };

/** Which menus a role may see. Checking a folder checks every program below it. */
export default function MenuPermission() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [modules, setModules] = useState<Module[]>([]);
  const [menus, setMenus] = useState<Menu[]>([]);
  const [role, setRole] = useState('');
  const [granted, setGranted] = useState<ReadonlySet<number>>(new Set());
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const fail = (cause: unknown) => setError(cause instanceof Error ? cause.message : '처리하지 못했습니다.');
  async function pick(code: string) { setRole(code); setSaved(false); setGranted(new Set(code ? await adminApi<number[]>(`/api/system/roles/${code}/menus`) : [])); }
  useEffect(() => { void (async () => {
    const list = (await adminApi<Role[]>('/api/system/roles')).filter(item => item.roleCode !== 'ADMIN');
    setRoles(list); setModules(await adminApi<Module[]>('/api/system/modules')); setMenus(await adminApi<Menu[]>('/api/system/menus'));
    if (list[0]) await pick(list[0].roleCode);
  })().catch(fail); }, []);
  const children = (module: string, parent: number | null) => menus.filter(menu => menu.moduleCode === module && menu.parentId === parent).sort((a, b) => a.sortOrder - b.sortOrder);
  const programsBelow = (menu: Menu): number[] => menu.menuType === 'PROGRAM' ? [menu.menuId] : children(menu.moduleCode, menu.menuId).flatMap(programsBelow);
  const toggle = (ids: number[], on: boolean) => { setSaved(false); setGranted(previous => { const next = new Set(previous); ids.forEach(id => { if (on) next.add(id); else next.delete(id); }); return next; }); };
  const node = (menu: Menu): TreeNode<Menu> => {
    const ids = programsBelow(menu);
    const count = ids.filter(id => granted.has(id)).length;
    return { id: menu.menuId, nodeData: menu, isExpanded: true, hasCaret: false,
      icon: <span className="sys-check"><Checkbox label={menu.menuName} hideLabel checked={ids.length > 0 && count === ids.length} indeterminate={count > 0 && count < ids.length}
        isDisabled={ids.length === 0} onChange={on => toggle(ids, on)} /><MenuIcon name={menu.menuType === 'FOLDER' ? 'folder' : 'document'} /></span>,
      label: menu.menuName, secondaryLabel: <span className="sys-muted">{menu.menuType === 'FOLDER' ? '폴더' : menu.programCode}</span>,
      childNodes: menu.menuType === 'FOLDER' ? children(menu.moduleCode, menu.menuId).map(node) : undefined };
  };
  return <div className="sys-page" data-ui="menu-permission">
    <div className="sys-head"><ScreenTitle>메뉴 권한 편성</ScreenTitle>
      <div className="sys-actions">
        <div style={{ width: 220 }}><Select label="역할" hideLabel value={role} onChange={value => void pick(value).catch(fail)}
          options={roles.length ? roles.map(item => ({ value: item.roleCode, label: `${item.roleName} (${item.roleCode})` })) : [{ value: '', label: '역할이 없습니다' }]} /></div>
        <Button label="저장" variant="primary" size="sm" isDisabled={!role}
          onClick={() => { setError(''); void adminApi(`/api/system/roles/${role}/menus`, 'PUT', { menuIds: [...granted] }).then(() => setSaved(true)).catch(fail); }} />
      </div></div>
    <AsyncFeedback error={error} succeeded={saved} successText="저장되었습니다. 처음 허용한 프로그램에는 조회 권한이 함께 부여됩니다." />
    <section className="sys-card bp6-card" aria-label="메뉴" style={{ flex: 1 }}>
      {modules.map(module => <div key={module.moduleCode}>
        <h3>{module.moduleName}</h3>
        <Tree<Menu> nodes={children(module.moduleCode, null).map(node)} onClick={() => undefined} onToggle={() => undefined} />
        {children(module.moduleCode, null).length === 0 && <div className="sys-muted">메뉴가 없습니다.</div>}
      </div>)}
    </section>
  </div>;
}

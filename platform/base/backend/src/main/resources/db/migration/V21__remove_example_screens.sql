-- The example screens 회사 등록 / 부서 등록 / 사원 등록 are removed so they can be built again from scratch.
-- (Their sources are kept in git under the tag before-rebuild-2026-11-11.) Tables, programs and menu entries go too.
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS departments;
DROP TABLE IF EXISTS companies;
DELETE FROM sys_user_favorites WHERE program_code IN ('MST0002', 'MST0003', 'MST0004');
DELETE FROM sys_role_programs WHERE program_code IN ('MST0002', 'MST0003', 'MST0004');
DELETE FROM sys_role_menus WHERE menu_id IN (SELECT menu_id FROM sys_menus WHERE program_code IN ('MST0002', 'MST0003', 'MST0004'));
DELETE FROM sys_menus WHERE program_code IN ('MST0002', 'MST0003', 'MST0004');
DELETE FROM sys_programs WHERE program_code IN ('MST0002', 'MST0003', 'MST0004');

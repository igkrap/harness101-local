-- The screens built as code files (회사·부서·사원·품목 등록) are removed; they are made again as definitions.
-- Their sources stay in git under the tag before-definitions-2026-11-11.
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS departments;
DROP TABLE IF EXISTS companies;
DROP TABLE IF EXISTS items;
DELETE FROM sys_user_favorites WHERE program_code LIKE 'MST%';
DELETE FROM sys_role_programs WHERE program_code LIKE 'MST%';
DELETE FROM sys_role_menus WHERE menu_id IN (SELECT menu_id FROM sys_menus WHERE program_code LIKE 'MST%');
DELETE FROM sys_menus WHERE program_code LIKE 'MST%';
DELETE FROM sys_programs WHERE program_code LIKE 'MST%';

-- 소메뉴 as a tree: a menu is a FOLDER (holds menus) or a PROGRAM (opens a screen); folders nest.
ALTER TABLE sys_menus ADD COLUMN parent_id BIGINT REFERENCES sys_menus(menu_id) ON DELETE CASCADE;
ALTER TABLE sys_menus ADD COLUMN menu_type VARCHAR(10) NOT NULL DEFAULT 'PROGRAM';
ALTER TABLE sys_menus ALTER COLUMN program_code DROP NOT NULL;
ALTER TABLE sys_menus ADD CONSTRAINT sys_menus_type_check
    CHECK ((menu_type = 'PROGRAM' AND program_code IS NOT NULL) OR (menu_type = 'FOLDER' AND program_code IS NULL));

-- The only module (대메뉴) to start with is 시스템; business modules are added by an administrator.
DELETE FROM sys_modules WHERE module_code = 'BASE';
UPDATE sys_modules SET module_name = '시스템', icon = 'settings', sort_order = 99 WHERE module_code = 'SYSTEM';

-- Organisation screens start under 시스템 > 조직 관리; other screens stay unplaced until modules exist.
INSERT INTO sys_programs (program_code, program_name, api_paths) VALUES
    ('MST0003', '부서 등록', '/api/departments'), ('MST0004', '사원 등록', '/api/employees')
ON CONFLICT (program_code) DO NOTHING;
INSERT INTO sys_menus (module_code, menu_type, menu_name, sort_order) VALUES ('SYSTEM', 'FOLDER', '조직 관리', 1);
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT f.module_code, f.menu_id, 'PROGRAM', p.program_code, p.program_name, x.ord
FROM (VALUES ('MST0003', 1), ('MST0004', 2)) AS x(program_code, ord)
JOIN sys_menus f ON f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '조직 관리'
JOIN sys_programs p ON p.program_code = x.program_code;

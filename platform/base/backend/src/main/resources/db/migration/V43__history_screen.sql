-- One screen for the history of every screen (registered, changed, moved on, deleted), placed with the system screens.
INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES
    ('SYS0013', '변경 이력', '/api/history', TRUE, '이력,변경 이력,삭제 이력,감사,누가 언제')
ON CONFLICT (program_code) DO NOTHING;
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT 'SYSTEM', f.menu_id, 'PROGRAM', 'SYS0013', '변경 이력', 13
FROM sys_menus f
WHERE f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '시스템 관리'
  AND NOT EXISTS (SELECT 1 FROM sys_menus m WHERE m.program_code = 'SYS0013');

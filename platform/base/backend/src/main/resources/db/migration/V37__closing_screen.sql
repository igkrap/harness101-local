-- The month-closing screen, placed with the other system screens.
INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES
    ('SYS0010', '마감 관리', '', TRUE, '마감,월 마감,결산,잠금')
ON CONFLICT (program_code) DO NOTHING;
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT 'SYSTEM', f.menu_id, 'PROGRAM', 'SYS0010', '마감 관리', 10
FROM sys_menus f
WHERE f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '시스템 관리'
  AND NOT EXISTS (SELECT 1 FROM sys_menus m WHERE m.program_code = 'SYS0010');

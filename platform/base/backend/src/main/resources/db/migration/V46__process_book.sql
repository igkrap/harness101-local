-- 업무 안내서: the system's processes read off the screen definitions (flows, master data by layer, every screen in sentences).
INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES
    ('SYS0015', '업무 안내서', '/api/meta/process', TRUE, '안내서,매뉴얼,업무 흐름,프로세스,사용법,도움말')
ON CONFLICT (program_code) DO NOTHING;
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT 'SYSTEM', f.menu_id, 'PROGRAM', 'SYS0015', '업무 안내서', 11
FROM sys_menus f
WHERE f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '시스템 관리'
  AND NOT EXISTS (SELECT 1 FROM sys_menus m WHERE m.program_code = 'SYS0015');

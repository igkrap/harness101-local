-- The framework's own administration screens, placed under 시스템 > 시스템 관리.
ALTER TABLE sys_programs ADD COLUMN keywords VARCHAR(500) NOT NULL DEFAULT '';

INSERT INTO sys_programs (program_code, program_name, api_paths, system_program) VALUES
    ('SYS0001', '사용자 관리', '', TRUE), ('SYS0002', '역할 관리', '', TRUE), ('SYS0003', '메뉴 편성', '', TRUE),
    ('SYS0004', '메뉴 권한 편성', '', TRUE), ('SYS0005', '프로그램 권한 편성', '', TRUE), ('SYS0006', '시스템 설정', '', TRUE)
ON CONFLICT (program_code) DO NOTHING;

INSERT INTO sys_menus (module_code, menu_type, menu_name, sort_order) VALUES ('SYSTEM', 'FOLDER', '시스템 관리', 0);
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT 'SYSTEM', f.menu_id, 'PROGRAM', p.program_code, p.program_name, CAST(RIGHT(p.program_code, 1) AS INT)
FROM sys_programs p
JOIN sys_menus f ON f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '시스템 관리'
WHERE p.program_code LIKE 'SYS000_';

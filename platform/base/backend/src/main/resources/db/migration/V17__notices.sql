-- Notices: written by administrators, read by everyone (home page ticker and the 공지사항 screen).
CREATE TABLE sys_notices (
    notice_id BIGSERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    published BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR(100) NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP
);
INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES
    ('SYS0009', '공지사항', '', TRUE, '공지,알림,게시판,게시글,안내')
ON CONFLICT (program_code) DO NOTHING;
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT 'SYSTEM', f.menu_id, 'PROGRAM', 'SYS0009', '공지사항', 9
FROM sys_menus f
WHERE f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '시스템 관리'
  AND NOT EXISTS (SELECT 1 FROM sys_menus m WHERE m.program_code = 'SYS0009');

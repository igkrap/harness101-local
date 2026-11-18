-- Common functions of the framework: common codes, password policy, who/when columns, access log.

-- Common codes: values of drop-downs kept by an administrator (group > code).
CREATE TABLE sys_code_groups (
    group_code VARCHAR(50) PRIMARY KEY,
    group_name VARCHAR(200) NOT NULL,
    description VARCHAR(500) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE sys_codes (
    group_code VARCHAR(50) NOT NULL REFERENCES sys_code_groups(group_code) ON DELETE CASCADE,
    code VARCHAR(50) NOT NULL,
    code_name VARCHAR(200) NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (group_code, code)
);
INSERT INTO sys_code_groups (group_code, group_name, description) VALUES ('USE_YN', '사용 여부', '사용/미사용 구분');
INSERT INTO sys_codes (group_code, code, code_name, sort_order) VALUES ('USE_YN', 'Y', '사용', 1), ('USE_YN', 'N', '미사용', 2);

-- Password policy (system settings) and when each password was last changed.
INSERT INTO sys_settings (setting_key, setting_value) VALUES
    ('password_min_length', '8'), ('password_require_mix', 'false'), ('password_require_special', 'false')
ON CONFLICT (setting_key) DO NOTHING;
ALTER TABLE workspace_users ADD COLUMN password_changed_at TIMESTAMP;

-- Access log: sign-ins, sign-outs, failed attempts and which programs were opened.
CREATE TABLE sys_access_logs (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    username VARCHAR(100) NOT NULL DEFAULT '',
    event VARCHAR(30) NOT NULL,          -- LOGIN | LOGIN_FAILED | LOGOUT | SESSION_REPLACED | PROGRAM_OPEN
    program_code VARCHAR(100),
    ip VARCHAR(64) NOT NULL DEFAULT '',
    detail VARCHAR(300) NOT NULL DEFAULT ''
);
CREATE INDEX sys_access_logs_time ON sys_access_logs (occurred_at DESC);

-- Who registered / last changed each business record, filled in automatically (AuditedEntity).
ALTER TABLE companies   ADD COLUMN created_by VARCHAR(100), ADD COLUMN created_at TIMESTAMP, ADD COLUMN updated_by VARCHAR(100), ADD COLUMN updated_at TIMESTAMP;
ALTER TABLE departments ADD COLUMN created_by VARCHAR(100), ADD COLUMN created_at TIMESTAMP, ADD COLUMN updated_by VARCHAR(100), ADD COLUMN updated_at TIMESTAMP;
ALTER TABLE employees   ADD COLUMN created_by VARCHAR(100), ADD COLUMN created_at TIMESTAMP, ADD COLUMN updated_by VARCHAR(100), ADD COLUMN updated_at TIMESTAMP;
ALTER TABLE items       ADD COLUMN created_by VARCHAR(100), ADD COLUMN created_at TIMESTAMP, ADD COLUMN updated_by VARCHAR(100), ADD COLUMN updated_at TIMESTAMP;

-- The two new administration screens, under 시스템 > 시스템 관리.
INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES
    ('SYS0007', '공통 코드 관리', '', TRUE, '공통코드,코드,선택값,콤보'), ('SYS0008', '접속 기록', '', TRUE, '로그,접속,사용 기록,로그인 기록')
ON CONFLICT (program_code) DO NOTHING;
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT 'SYSTEM', f.menu_id, 'PROGRAM', p.program_code, p.program_name, CAST(RIGHT(p.program_code, 1) AS INT)
FROM sys_programs p
JOIN sys_menus f ON f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '시스템 관리'
WHERE p.program_code IN ('SYS0007', 'SYS0008')
  AND NOT EXISTS (SELECT 1 FROM sys_menus m WHERE m.program_code = p.program_code);

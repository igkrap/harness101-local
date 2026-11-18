-- Common system framework: role-based access, system / module (대메뉴) / menu (소메뉴), programs.
-- Programs are screens; they register themselves (sync) and an administrator places them in menus.

ALTER TABLE workspace_users ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';   -- PENDING | ACTIVE | REJECTED | LOCKED
ALTER TABLE workspace_users ADD COLUMN email VARCHAR(200);
ALTER TABLE workspace_users ADD COLUMN requested_at TIMESTAMP;
ALTER TABLE workspace_users ADD COLUMN approved_by VARCHAR(100);
ALTER TABLE workspace_users ADD COLUMN approved_at TIMESTAMP;

CREATE TABLE sys_roles (
    role_code VARCHAR(50) PRIMARY KEY,
    role_name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sys_user_roles (
    username VARCHAR(100) NOT NULL REFERENCES workspace_users(username) ON DELETE CASCADE,
    role_code VARCHAR(50) NOT NULL REFERENCES sys_roles(role_code) ON DELETE CASCADE,
    PRIMARY KEY (username, role_code)
);

CREATE TABLE sys_systems (
    system_code VARCHAR(50) PRIMARY KEY,
    system_name VARCHAR(100) NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sys_modules (
    module_code VARCHAR(50) PRIMARY KEY,
    system_code VARCHAR(50) NOT NULL REFERENCES sys_systems(system_code),
    module_name VARCHAR(100) NOT NULL,
    icon VARCHAR(50),
    sort_order INT NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sys_programs (
    program_code VARCHAR(50) PRIMARY KEY,
    program_name VARCHAR(100) NOT NULL,
    api_paths VARCHAR(1000) NOT NULL DEFAULT '',     -- comma separated API prefixes this screen uses, e.g. /api/items
    system_program BOOLEAN NOT NULL DEFAULT FALSE,   -- framework's own administration screens
    registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sys_menus (
    menu_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    module_code VARCHAR(50) NOT NULL REFERENCES sys_modules(module_code) ON DELETE CASCADE,
    program_code VARCHAR(50) NOT NULL UNIQUE REFERENCES sys_programs(program_code) ON DELETE CASCADE,
    menu_name VARCHAR(100) NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sys_role_menus (
    role_code VARCHAR(50) NOT NULL REFERENCES sys_roles(role_code) ON DELETE CASCADE,
    menu_id BIGINT NOT NULL REFERENCES sys_menus(menu_id) ON DELETE CASCADE,
    PRIMARY KEY (role_code, menu_id)
);

CREATE TABLE sys_role_programs (
    role_code VARCHAR(50) NOT NULL REFERENCES sys_roles(role_code) ON DELETE CASCADE,
    program_code VARCHAR(50) NOT NULL REFERENCES sys_programs(program_code) ON DELETE CASCADE,
    can_query BOOLEAN NOT NULL DEFAULT TRUE,
    can_create BOOLEAN NOT NULL DEFAULT FALSE,
    can_save BOOLEAN NOT NULL DEFAULT FALSE,
    can_delete BOOLEAN NOT NULL DEFAULT FALSE,
    can_print BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (role_code, program_code)
);

INSERT INTO sys_roles (role_code, role_name, description) VALUES
    ('ADMIN', '관리자', '모든 메뉴와 프로그램을 사용할 수 있고 시스템을 관리한다'),
    ('USER', '일반 사용자', '편성된 메뉴와 권한만 사용한다');

INSERT INTO sys_systems (system_code, system_name, sort_order) VALUES ('MAIN', '업무 시스템', 1);
INSERT INTO sys_modules (module_code, system_code, module_name, icon, sort_order) VALUES
    ('BASE', 'MAIN', '기준정보', 'box', 1),
    ('SYSTEM', 'MAIN', '시스템 관리', 'settings', 99);

-- Existing administrators keep full access through the ADMIN role.
INSERT INTO sys_user_roles (username, role_code)
SELECT username, 'ADMIN' FROM workspace_users WHERE permissions LIKE '%workspace:admin%';

-- System identity and look: name (also the browser tab title), logo, favicon, theme.
CREATE TABLE sys_settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value TEXT NOT NULL DEFAULT ''
);
INSERT INTO sys_settings (setting_key, setting_value) VALUES
    ('system_name', '제조시스템'),
    ('logo', ''),            -- image as a data: URL (png/svg/jpeg/webp), empty = initial letter mark
    ('favicon', ''),         -- image as a data: URL, empty = logo or default
    ('theme_color', '#2d72d2'),
    ('theme_mode', 'light'); -- light | dark

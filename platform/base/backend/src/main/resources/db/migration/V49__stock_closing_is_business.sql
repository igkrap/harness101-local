-- 수불 마감 is stock work, not system administration: an ordinary program (given to roles like any work screen) on its own path,
-- placed in a 재고 module instead of 시스템 관리.
UPDATE sys_programs SET system_program = FALSE, api_paths = '/api/stock-closings' WHERE program_code = 'SYS0014';
INSERT INTO sys_modules (module_code, system_code, module_name, icon, sort_order, enabled)
SELECT 'STOCK', system_code, '재고', 'warehouse', 10, TRUE FROM sys_modules WHERE module_code = 'SYSTEM'
ON CONFLICT (module_code) DO NOTHING;
UPDATE sys_menus SET module_code = 'STOCK', parent_id = NULL, sort_order = 1 WHERE program_code = 'SYS0014';

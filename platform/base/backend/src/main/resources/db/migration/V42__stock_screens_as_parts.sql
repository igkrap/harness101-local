-- The stock screens made by hand are gone: stock is seen and counted through screens made from definitions (stockView, stock.direction count).
DELETE FROM sys_role_menus WHERE menu_id IN (SELECT menu_id FROM sys_menus WHERE program_code IN ('SYS0011', 'SYS0012'));
DELETE FROM sys_menus WHERE program_code IN ('SYS0011', 'SYS0012');
DELETE FROM sys_role_programs WHERE program_code IN ('SYS0011', 'SYS0012');
DELETE FROM sys_programs WHERE program_code IN ('SYS0011', 'SYS0012');

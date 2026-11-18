-- Period locks: a part that knows no business. Definitions name the lock group their records belong to ("lock": {"group", "date"});
-- each group is locked month by month. What was 수불 마감 becomes the group 수불 of the screens that say so.
CREATE TABLE period_locks (
    lock_group VARCHAR(60) NOT NULL,
    period CHAR(7) NOT NULL,                     -- 2026-10
    closed_by VARCHAR(100),
    closed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note VARCHAR(300),
    PRIMARY KEY (lock_group, period)
);
CREATE TABLE period_lock_balances (
    lock_group VARCHAR(60) NOT NULL,
    period CHAR(7) NOT NULL,
    item_id BIGINT NOT NULL, warehouse_id BIGINT, lot_id BIGINT NOT NULL,
    quantity NUMERIC NOT NULL, amount NUMERIC NOT NULL,
    PRIMARY KEY (lock_group, period, lot_id),
    FOREIGN KEY (lock_group, period) REFERENCES period_locks (lock_group, period) ON DELETE CASCADE
);
INSERT INTO period_locks (lock_group, period, closed_by, closed_at, note) SELECT '수불', period, closed_by, closed_at, note FROM stock_closings;
INSERT INTO period_lock_balances (lock_group, period, item_id, warehouse_id, lot_id, quantity, amount)
    SELECT '수불', period, item_id, warehouse_id, lot_id, quantity, amount FROM stock_closing_balances;
DROP TABLE stock_closing_balances;
DROP TABLE stock_closings;

-- The screen is the general 마감 (a page per lock group); a project places it in its menus when it has a group to lock.
UPDATE sys_programs SET program_name = '마감', api_paths = '/api/locks', system_program = FALSE, keywords = '마감,월 마감,기간 마감,잠금' WHERE program_code = 'SYS0014';
DELETE FROM sys_menus WHERE program_code = 'SYS0014';
DELETE FROM sys_modules m WHERE m.module_code = 'STOCK' AND NOT EXISTS (SELECT 1 FROM sys_menus x WHERE x.module_code = m.module_code);

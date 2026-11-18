-- Closing is the stock's: a closed month takes no stock movement (no receipt, issue, move, count or adjustment dated in it,
-- and no change to a record whose stock moved in it). Months are closed in order and only the newest closed one is opened again.
-- What each item had at the end of a closed month (by warehouse and lot, quantity and amount) is kept with it.
DROP TABLE IF EXISTS sys_closings;
DELETE FROM sys_programs WHERE program_code = 'SYS0010';

CREATE TABLE stock_closings (
    period CHAR(7) PRIMARY KEY,                 -- 2026-10
    closed_by VARCHAR(100),
    closed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note VARCHAR(300)
);
CREATE TABLE stock_closing_balances (
    period CHAR(7) NOT NULL REFERENCES stock_closings(period) ON DELETE CASCADE,
    item_id BIGINT NOT NULL, warehouse_id BIGINT, lot_id BIGINT NOT NULL,
    quantity NUMERIC NOT NULL, amount NUMERIC NOT NULL,
    PRIMARY KEY (period, lot_id)
);

INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES
    ('SYS0014', '수불 마감', '/api/system/stock/closings', TRUE, '마감,수불 마감,월 마감,재고 마감,기말 재고')
ON CONFLICT (program_code) DO NOTHING;
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT 'SYSTEM', f.menu_id, 'PROGRAM', 'SYS0014', '수불 마감', 10
FROM sys_menus f
WHERE f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '시스템 관리'
  AND NOT EXISTS (SELECT 1 FROM sys_menus m WHERE m.program_code = 'SYS0014');

-- The change history screen stays (it can be put on a menu again); it is not on the menu for now. An empty folder goes.
DELETE FROM sys_menus WHERE program_code = 'SYS0013';
DELETE FROM sys_menus f WHERE f.menu_type = 'FOLDER' AND f.menu_name = '조직 관리'
  AND NOT EXISTS (SELECT 1 FROM sys_menus c WHERE c.parent_id = f.menu_id);

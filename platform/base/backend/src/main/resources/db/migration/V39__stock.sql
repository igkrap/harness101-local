-- Stock, kept by lot. A lot is what one line of a receiving record brought in: an item in a warehouse at a unit cost.
-- Every movement is a row of the ledger (stock_moves); an issue takes from the oldest lots first and carries each lot's cost.
CREATE TABLE stock_lots (
    lot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_no VARCHAR(40) UNIQUE,
    item_entity VARCHAR(50) NOT NULL, item_id BIGINT NOT NULL,
    warehouse_entity VARCHAR(50), warehouse_id BIGINT,
    unit_cost NUMERIC NOT NULL DEFAULT 0,
    received_qty NUMERIC NOT NULL, remaining_qty NUMERIC NOT NULL,
    received_on DATE NOT NULL,
    source_entity VARCHAR(50) NOT NULL, source_id BIGINT NOT NULL, source_line INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX stock_lots_open ON stock_lots (item_id, warehouse_id, received_on, lot_id) WHERE remaining_qty > 0;
CREATE INDEX stock_lots_source ON stock_lots (source_entity, source_id);
CREATE TABLE stock_moves (
    move_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_key VARCHAR(50) NOT NULL, record_id BIGINT NOT NULL, line_no INT NOT NULL,
    direction VARCHAR(3) NOT NULL,                 -- IN | OUT
    item_id BIGINT NOT NULL, warehouse_id BIGINT, lot_id BIGINT NOT NULL REFERENCES stock_lots(lot_id),
    quantity NUMERIC NOT NULL, unit_cost NUMERIC NOT NULL, amount NUMERIC NOT NULL,
    moved_on DATE NOT NULL, created_by VARCHAR(100), created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX stock_moves_record ON stock_moves (entity_key, record_id);
CREATE INDEX stock_moves_item ON stock_moves (item_id, moved_on);
CREATE INDEX stock_moves_lot ON stock_moves (lot_id);
INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES
    ('SYS0011', '재고 현황', '/api/stock', TRUE, '재고,현재고,LOT,로트,수불,원가')
ON CONFLICT (program_code) DO NOTHING;
INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order)
SELECT 'SYSTEM', f.menu_id, 'PROGRAM', 'SYS0011', '재고 현황', 11
FROM sys_menus f
WHERE f.module_code = 'SYSTEM' AND f.menu_type = 'FOLDER' AND f.menu_name = '시스템 관리'
  AND NOT EXISTS (SELECT 1 FROM sys_menus m WHERE m.program_code = 'SYS0011');

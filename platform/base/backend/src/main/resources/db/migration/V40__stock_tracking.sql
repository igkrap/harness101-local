-- How an item's stock is kept, chosen per item: by quantity only, or by lot (a lot number a person gives and can ask for when issuing).
INSERT INTO sys_code_groups (group_code, group_name, description) VALUES ('STOCK_TRACKING', '재고 관리 방식', '품목마다 재고를 수량만으로 관리할지 LOT 로 관리할지')
ON CONFLICT (group_code) DO NOTHING;
INSERT INTO sys_codes (group_code, code, code_name, sort_order) VALUES ('STOCK_TRACKING', 'NONE', '수량만', 1), ('STOCK_TRACKING', 'LOT', 'LOT 관리', 2)
ON CONFLICT (group_code, code) DO NOTHING;
-- A lot number given by a person may come in more than once (two receipts of the same maker's lot): each receipt stays a lot of its own, with its own cost.
ALTER TABLE stock_lots DROP CONSTRAINT IF EXISTS stock_lots_lot_no_key;
CREATE INDEX stock_lots_number ON stock_lots (item_id, lot_no);

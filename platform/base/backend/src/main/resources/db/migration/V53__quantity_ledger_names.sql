-- The quantity ledger knows no business: things at places, moved in and out, counted, kept by numbered lots.
ALTER TABLE stock_lots RENAME TO ledger_lots;
ALTER TABLE ledger_lots RENAME COLUMN item_entity TO thing_entity;
ALTER TABLE ledger_lots RENAME COLUMN item_id TO thing_id;
ALTER TABLE ledger_lots RENAME COLUMN warehouse_entity TO place_entity;
ALTER TABLE ledger_lots RENAME COLUMN warehouse_id TO place_id;
ALTER TABLE stock_moves RENAME TO ledger_moves;
ALTER TABLE ledger_moves RENAME COLUMN item_id TO thing_id;
ALTER TABLE ledger_moves RENAME COLUMN warehouse_id TO place_id;
ALTER TABLE period_lock_balances RENAME COLUMN item_id TO thing_id;
ALTER TABLE period_lock_balances RENAME COLUMN warehouse_id TO place_id;
ALTER INDEX IF EXISTS stock_lots_open RENAME TO ledger_lots_open;
ALTER INDEX IF EXISTS stock_lots_source RENAME TO ledger_lots_source;
ALTER INDEX IF EXISTS stock_moves_record RENAME TO ledger_moves_record;
ALTER INDEX IF EXISTS stock_moves_item RENAME TO ledger_moves_thing;
ALTER INDEX IF EXISTS stock_moves_lot RENAME TO ledger_moves_lot;

-- Definitions as stored: "stock" (item / warehouse / toWarehouse) becomes "ledger" (thing / place / toPlace), "stockView" becomes "ledgerView".
UPDATE app_definitions
SET definition = ((definition::jsonb - 'stock' - 'stockView')
    || CASE WHEN jsonb_typeof(definition::jsonb -> 'stock') = 'object' THEN jsonb_build_object('ledger',
          ((definition::jsonb -> 'stock') - 'item' - 'warehouse' - 'toWarehouse' - 'itemEntity' - 'warehouseEntity')
          || jsonb_build_object('thing', definition::jsonb -> 'stock' -> 'item', 'place', definition::jsonb -> 'stock' -> 'warehouse',
                                'toPlace', definition::jsonb -> 'stock' -> 'toWarehouse', 'thingEntity', definition::jsonb -> 'stock' -> 'itemEntity',
                                'placeEntity', definition::jsonb -> 'stock' -> 'warehouseEntity')) ELSE '{}'::jsonb END
    || CASE WHEN jsonb_typeof(definition::jsonb -> 'stockView') = 'object' THEN jsonb_build_object('ledgerView', definition::jsonb -> 'stockView') ELSE '{}'::jsonb END
    || CASE WHEN definition::jsonb ->> 'type' = 'stockView' THEN '{"type": "ledgerView"}'::jsonb ELSE '{}'::jsonb END)::text
WHERE definition::jsonb ? 'stock' OR definition::jsonb ? 'stockView';

UPDATE sys_programs SET api_paths = replace(api_paths, '/api/stock/', '/api/ledger/') WHERE api_paths LIKE '%/api/stock/%';

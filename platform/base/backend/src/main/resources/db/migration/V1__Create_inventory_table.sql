CREATE TABLE inventory (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    min_quantity INTEGER NOT NULL CHECK (min_quantity >= 0),
    unit_price NUMERIC(19, 2) NOT NULL CHECK (unit_price >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO inventory (name, category, quantity, min_quantity, unit_price, created_at) VALUES
('고춧가루', '양념', 10, 2, 15000.00, NOW()),
('참기름', '양념', 5, 1, 25000.00, NOW()),
('쌀', '곡류', 20, 5, 30000.00, NOW()),
('설탕', '조미료', 15, 3, 5000.00, NOW()),
('간장', '조미료', 8, 2, 8000.00, NOW()),
('소금', '조미료', 12, 2, 2000.00, NOW());

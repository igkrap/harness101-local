CREATE TABLE items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_code TEXT NOT NULL,
    item_name TEXT NOT NULL,
    specification TEXT,
    unit TEXT,
    remark TEXT
);

CREATE TABLE faxes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fax VARCHAR(30) NOT NULL,
    created_by VARCHAR(100),
    created_at TIMESTAMP,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP
);

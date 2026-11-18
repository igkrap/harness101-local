-- Definition-driven screens: what a screen manages is data (a definition), not generated code.
-- app_definitions holds each entity's definition (fields, lookups); app_records holds every entity's rows.
CREATE TABLE app_definitions (
    entity_key VARCHAR(50) PRIMARY KEY,               -- e.g. customer
    program_code VARCHAR(50) NOT NULL UNIQUE,         -- menu / permission identity, e.g. APP0001
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',      -- DRAFT (administrators and checks only) | PUBLISHED
    definition TEXT NOT NULL,                         -- JSON: title, keywords, fields
    revision INT NOT NULL DEFAULT 1,
    created_by VARCHAR(100), created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100), updated_at TIMESTAMP
);
CREATE TABLE app_records (
    id BIGSERIAL PRIMARY KEY,
    entity_key VARCHAR(50) NOT NULL,
    data JSONB NOT NULL,
    created_by VARCHAR(100), created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100), updated_at TIMESTAMP
);
CREATE INDEX app_records_entity ON app_records (entity_key, id);

-- Files attached to a record (a quotation as PDF, a photograph of a defect ...). Kept in the database so that a backup,
-- a restore and a move to another server carry them along with the records they belong to.
CREATE TABLE app_record_files (
    file_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_key VARCHAR(50) NOT NULL,
    record_id BIGINT NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    content_type VARCHAR(150) NOT NULL DEFAULT 'application/octet-stream',
    size_bytes BIGINT NOT NULL,
    content BYTEA NOT NULL,
    created_by VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX app_record_files_record ON app_record_files (entity_key, record_id, file_id);

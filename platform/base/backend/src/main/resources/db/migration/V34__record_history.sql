-- Who changed what and when: one row per registration, change, status action and deletion of a record.
-- before/after hold the record's values around the change (null before a registration, null after a deletion).
CREATE TABLE app_record_history (
    history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_key VARCHAR(50) NOT NULL,
    record_id BIGINT NOT NULL,
    action VARCHAR(20) NOT NULL,            -- CREATE | UPDATE | STATUS | DELETE
    action_name VARCHAR(100),               -- the status action taken (confirm, cancel ...)
    automatic BOOLEAN NOT NULL DEFAULT FALSE,   -- done by an effect of another record, not by a person's own hand
    before_data JSONB,
    after_data JSONB,
    status_before VARCHAR(30),
    status_after VARCHAR(30),
    changed_by VARCHAR(100),
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX app_record_history_record ON app_record_history (entity_key, record_id, history_id);

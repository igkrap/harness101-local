-- Things a person should know about: a record waiting on a screen they have, or a change to a record they entered.
CREATE TABLE sys_notifications (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    message VARCHAR(400) NOT NULL,
    program_code VARCHAR(50),
    entity_key VARCHAR(60),
    record_id BIGINT,
    created_by VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP
);
CREATE INDEX idx_sys_notifications_user ON sys_notifications (username, read_at, id DESC);

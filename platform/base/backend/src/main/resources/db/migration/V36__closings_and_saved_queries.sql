-- Months that are closed: records whose closing date falls in one cannot be registered, changed, acted on or deleted.
CREATE TABLE sys_closings (
    period CHAR(7) PRIMARY KEY,                 -- 2026-10
    closed_by VARCHAR(100),
    closed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note VARCHAR(300)
);
-- Query conditions a person keeps for a screen, to use again with one click.
CREATE TABLE sys_user_queries (
    query_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    program_code VARCHAR(50) NOT NULL,
    query_name VARCHAR(60) NOT NULL,
    query_values TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (username, program_code, query_name)
);

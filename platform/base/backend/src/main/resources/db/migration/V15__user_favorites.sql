-- Each user's favourite programs (shown at the top of the sidebar).
CREATE TABLE sys_user_favorites (
    username VARCHAR(100) NOT NULL REFERENCES workspace_users(username) ON DELETE CASCADE,
    program_code VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (username, program_code)
);

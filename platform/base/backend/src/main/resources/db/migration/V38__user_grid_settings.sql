-- How a person has arranged a table of a screen (their own only): hidden columns, column order, column widths.
CREATE TABLE sys_user_grids (
    username VARCHAR(100) NOT NULL,
    grid_key VARCHAR(160) NOT NULL,             -- program code : table name
    settings TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (username, grid_key)
);

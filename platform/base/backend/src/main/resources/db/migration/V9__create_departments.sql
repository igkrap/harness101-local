CREATE TABLE departments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dept_code TEXT NOT NULL,
    dept_name TEXT NOT NULL,
    parent_dept_code TEXT
);

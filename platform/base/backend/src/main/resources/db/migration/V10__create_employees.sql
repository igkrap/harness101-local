CREATE TABLE employees (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    department TEXT,
    position TEXT,
    email TEXT,
    phone TEXT
);

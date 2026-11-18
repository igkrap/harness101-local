CREATE TABLE employees (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    employee_number TEXT NOT NULL,
    department_id BIGINT,
    phone TEXT,
    email TEXT,
    hire_date DATE,
    position VARCHAR(50),
    status VARCHAR(50),
    created_by VARCHAR(100),
    created_at TIMESTAMP,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP
);

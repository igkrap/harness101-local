CREATE TABLE companies (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_name TEXT NOT NULL,
    business_number VARCHAR(50) NOT NULL,
    representative TEXT,
    address TEXT,
    phone TEXT,
    email TEXT,
    created_by VARCHAR(100),
    created_at TIMESTAMP,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP
);

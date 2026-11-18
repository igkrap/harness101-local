CREATE TABLE companies (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    business_registration_number TEXT,
    address TEXT,
    phone TEXT,
    contact_person TEXT
);

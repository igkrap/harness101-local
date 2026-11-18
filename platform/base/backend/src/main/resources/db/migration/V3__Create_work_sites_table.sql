CREATE TABLE work_sites (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO work_sites (name, location, created_at) VALUES
('제1 공장', '서울시 성동구', NOW()),
('제2 공장', '경기도 안산시', NOW());

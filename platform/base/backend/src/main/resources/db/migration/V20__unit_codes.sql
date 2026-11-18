-- Units as a common-code group, used by the reference screen (품목 등록) and by new screens that need a unit.
INSERT INTO sys_code_groups (group_code, group_name, description) VALUES ('UNIT', '단위', '수량 단위')
ON CONFLICT (group_code) DO NOTHING;
INSERT INTO sys_codes (group_code, code, code_name, sort_order) VALUES
    ('UNIT', 'EA', '개', 1), ('UNIT', 'BOX', '박스', 2), ('UNIT', 'SET', '세트', 3), ('UNIT', 'KG', 'kg', 4), ('UNIT', 'M', 'm', 5)
ON CONFLICT (group_code, code) DO NOTHING;

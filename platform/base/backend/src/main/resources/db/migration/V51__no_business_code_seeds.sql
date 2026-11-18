-- Business code groups are the definitions' to declare ("codeGroups"), not the framework's to seed: the units and the stock-keeping
-- methods an earlier version put in every project go wherever no screen chooses from them (a project that uses them keeps them).
DELETE FROM sys_code_groups g
WHERE g.group_code IN ('UNIT', 'STOCK_TRACKING')
  AND NOT EXISTS (SELECT 1 FROM app_definitions d WHERE jsonb_path_exists(d.definition::jsonb, '$.** ? (@.codeGroup == $g)', jsonb_build_object('g', g.group_code)));

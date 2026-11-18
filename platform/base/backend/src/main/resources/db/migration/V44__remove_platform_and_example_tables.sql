-- The project's database holds the system's own tables only. Gone: what the platform's earlier way of working (screen specification
-- documents) kept here, the first example screens, and the single table records were kept in before every screen had its own.
DROP TABLE IF EXISTS development_validation_runs;
DROP TABLE IF EXISTS development_screen_bindings;
DROP TABLE IF EXISTS development_spec_releases;
DROP TABLE IF EXISTS development_spec_documents;
DROP TABLE IF EXISTS spec_demo_contacts;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS work_sites;
-- (the ids every screen's records take come from the sequence the single table owned: it is kept, under a name of its own)
ALTER SEQUENCE IF EXISTS app_records_id_seq OWNED BY NONE;
ALTER SEQUENCE IF EXISTS app_records_id_seq RENAME TO app_record_ids;
DROP TABLE IF EXISTS app_records;

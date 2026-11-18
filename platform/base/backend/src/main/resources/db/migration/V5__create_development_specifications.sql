CREATE TABLE IF NOT EXISTS development_spec_documents (
    kind varchar(16) NOT NULL CHECK (kind IN ('entity','operation','screen')),
    document_id varchar(100) NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    definition jsonb NOT NULL,
    sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, document_id, revision)
);
CREATE TABLE IF NOT EXISTS development_spec_releases (
    screen_code char(7) NOT NULL CHECK (screen_code ~ '^[A-Z]{3}[0-9]{4}$'),
    revision integer NOT NULL CHECK (revision > 0),
    manifest jsonb NOT NULL,
    sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (screen_code, revision)
);
CREATE TABLE IF NOT EXISTS development_screen_bindings (
    screen_code char(7) PRIMARY KEY,
    revision integer NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (screen_code, revision) REFERENCES development_spec_releases(screen_code, revision)
);
CREATE TABLE IF NOT EXISTS development_validation_runs (
    run_id varchar(32) PRIMARY KEY,
    screen_code char(7) NOT NULL,
    revision integer NOT NULL,
    spec_sha256 char(64) NOT NULL,
    executor varchar(200) NOT NULL,
    status varchar(32) NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (screen_code, revision) REFERENCES development_spec_releases(screen_code, revision)
);

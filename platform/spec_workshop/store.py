import json
import pathlib
import re
import subprocess
from .contracts import canonical, digest, require, validate

ROOT = pathlib.Path(__file__).resolve().parents[2]


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


class Store:
    def __init__(self, database='mdi_local'):
        require(bool(re.fullmatch(r'[a-z][a-z0-9_]{0,62}', database)), 'Invalid database name')
        self.database = database

    def sql(self, statement):
        result = subprocess.run(['docker', 'exec', '-i', 'mdi-db', 'psql', '-U', 'mdi', '-d', self.database,
                                 '-At', '-v', 'ON_ERROR_STOP=1'], input=statement, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result.stdout.strip()

    def initialize(self):
        self.sql((ROOT/'local-only/backend/src/main/resources/db/migration/V5__create_development_specifications.sql').read_text())

    def put(self, kind, document_id, revision, definition):
        require(kind in ('entity', 'operation', 'screen') and type(revision) is int and revision > 0, 'Invalid document key')
        stamp = digest(definition)
        key = f"kind={literal(kind)} AND document_id={literal(document_id)} AND revision={revision}"
        self.sql(f"INSERT INTO development_spec_documents(kind,document_id,revision,definition,sha256) VALUES ({literal(kind)},{literal(document_id)},{revision},{literal(canonical(definition))}::jsonb,{literal(stamp)}) ON CONFLICT DO NOTHING;")
        require(self.sql('SELECT sha256 FROM development_spec_documents WHERE '+key+';') == stamp, 'Immutable document revision already exists with different content')
        return {'kind': kind, 'id': document_id, 'revision': revision, 'sha256': stamp}

    def release(self, bundle, revision):
        validate(bundle)
        refs = {'entity': self.put('entity', bundle['entity']['id'], revision, bundle['entity']),
                'screen': self.put('screen', bundle['screen']['code'], revision, bundle['screen']),
                'operations': {kind: self.put('operation', operation['id'], revision, operation) for kind, operation in bundle['operations'].items()}}
        code, stamp = bundle['screen']['code'], digest(bundle)
        manifest = {'references': refs, 'bundleSha256': stamp}
        self.sql(f"INSERT INTO development_spec_releases(screen_code,revision,manifest,sha256) VALUES ({literal(code)},{revision},{literal(canonical(manifest))}::jsonb,{literal(stamp)}) ON CONFLICT DO NOTHING;")
        loaded = self.load(code, revision)
        require(digest(loaded) == stamp, 'Immutable release revision already differs')
        return manifest

    def load(self, code, revision):
        require(bool(re.fullmatch(r'[A-Z]{3}[0-9]{4}', code)) and type(revision) is int and revision > 0, 'Invalid release key')
        raw = self.sql(f'SELECT manifest::text FROM development_spec_releases WHERE screen_code={literal(code)} AND revision={revision};')
        require(bool(raw), 'Release not found')
        manifest = json.loads(raw)
        def read(ref):
            value = json.loads(self.sql(f"SELECT definition::text FROM development_spec_documents WHERE kind={literal(ref['kind'])} AND document_id={literal(ref['id'])} AND revision={int(ref['revision'])};"))
            require(digest(value) == ref['sha256'], 'Document hash mismatch')
            return value
        refs = manifest['references']
        bundle = {'entity': read(refs['entity']), 'screen': read(refs['screen']), 'operations': {kind: read(ref) for kind, ref in refs['operations'].items()}}
        require(digest(bundle) == manifest['bundleSha256'], 'Release hash mismatch')
        return validate(bundle)

    def activate(self, code, revision, provision=False):
        from .contracts import ddl
        bundle = self.load(code, revision)
        table = bundle['entity']['table']
        exists = self.sql(f"SELECT EXISTS(SELECT FROM information_schema.tables WHERE table_schema='public' AND table_name={literal(table)});") == 't'
        if not exists:
            require(provision, 'Entity table needs an explicit migration/provision step')
            self.sql(ddl(bundle))
        columns = self.sql(f"SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name={literal(table)} ORDER BY ordinal_position;").splitlines()
        require(columns == [f['column'] for f in bundle['entity']['fields']], 'Database columns differ from the released entity')
        self.sql(f"INSERT INTO development_screen_bindings(screen_code,revision) VALUES ({literal(code)},{revision}) ON CONFLICT(screen_code) DO UPDATE SET revision=EXCLUDED.revision,updated_at=now();")
        return {'screenCode':code,'revision':revision,'sha256':digest(bundle),'active':True}

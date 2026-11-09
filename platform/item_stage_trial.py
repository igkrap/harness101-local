"""Run one small item-screen task; preserve a passed stage for the next task."""
import argparse
from pathlib import PurePosixPath
import re
import sys

from item_crud_trial import ROOT, TARGET, main


def layout_change(path):
    return path in (TARGET, 'frontend/src/workspace.json')


def query_change(path):
    return path == TARGET


def api_query_change(path):
    return False


def backend_existing_source(path):
    if '..' in PurePosixPath(path).parts or '\\' in path:
        return False
    return bool(re.fullmatch(r'backend/src/main/java/com/example/localinventory/.+\.java', path))


def frontend_new_source(path):
    parts = PurePosixPath(path).parts
    if '..' in parts:
        return False
    return (path.startswith('frontend/src/') and not path.startswith('frontend/src/framework/')
            and path.endswith(('.ts', '.tsx')) and not path.endswith('.d.ts'))


def backend_new_source(path):
    if '..' in PurePosixPath(path).parts:
        return False
    if re.fullmatch(r'backend/src/(?:main|test)/java/com/example/localinventory/.+\.java', path):
        return True
    return bool(re.fullmatch(r'backend/src/main/resources/db/migration/V[0-9]+(?:[._][0-9]+)*__[^/]+\.sql', path))


def query_new_source(path):
    return frontend_new_source(path) or backend_new_source(path)


STAGES = {
    'layout': {
        'acceptance': 'item-master-layout-v1',
        'checks': ['frontend', 'framework'],
        'max_calls': 24,
        'max_tokens': 8192,
        'wall_seconds': 1200,
        'thinking': False,
        'context_profile': 'focused',
        'allowed': layout_change,
        'require_clean_start': True,
        'evidence_prefix': 'item-layout-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Layout only; existing login service, no business API or DB writes',
    },
    'query': {
        'acceptance': 'item-master-query-v1',
        'checks': ['frontend', 'backend', 'framework'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': False,
        'context_profile': 'focused',
        'allowed': query_change,
        'allowed_new': query_new_source,
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-query-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Fresh owned database/backend with fixed query fixture; GET-only business API; existing live database unchanged',
    },
    'api-query': {
        'acceptance': 'item-master-api-query-v1',
        'checks': ['backend'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': True,
        'context_profile': 'focused',
        'allowed': api_query_change,
        'allowed_new': backend_new_source,
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-api-query-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Fresh owned database/backend with fixed fixture; query API only; existing frontend and live database unchanged',
    },
    'query-ui': {
        'acceptance': 'item-master-query-ui-v1',
        'checks': ['frontend', 'framework'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': True,
        'context_profile': 'focused',
        'allowed': query_change,
        'allowed_new': frontend_new_source,
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-query-ui-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Use the verified query backend unchanged in a fresh owned database; fixed fixture and GET-only business calls',
    },
    'create-ui': {
        'acceptance': 'item-master-create-ui-v1',
        'checks': ['frontend', 'framework'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': False,
        'context_profile': 'focused',
        'allowed': query_change,
        'allowed_new': frontend_new_source,
        'approved_success_dirs': tuple(ROOT / 'platform/state/evidence' / name for name in (
            'item-layout-20261105-005241',
            'item-api-query-20261105-045137',
            'item-query-ui-instruct-20261105-053626',
            'item-api-create-policy-repair-20261105-082420',
        )),
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-create-ui-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Verified backend unchanged; isolated browser POST and SQL persistence; independent query regression and owned runtime cleanup',
    },
    'update-ui': {
        'acceptance': 'item-master-update-ui-v1',
        'checks': ['frontend', 'framework'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': False,
        'context_profile': 'focused',
        'allowed': query_change,
        'allowed_new': frontend_new_source,
        'approved_success_dirs': tuple(ROOT / 'platform/state/evidence' / name for name in (
            'item-layout-20261105-005241',
            'item-api-query-20261105-045137',
            'item-query-ui-instruct-20261105-053626',
            'item-api-create-policy-repair-20261105-082420',
            'item-create-ui-20261105-141936',
            'item-api-update-20261105-143733',
        )),
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-update-ui-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Verified backend unchanged; browser PUT and SQL persistence with independent query/create regression and all owned runtime cleanup',
    },
    'delete-ui': {
        'acceptance': 'item-master-delete-ui-v1',
        'checks': ['frontend', 'framework'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': False,
        'context_profile': 'focused',
        'allowed': query_change,
        'allowed_new': frontend_new_source,
        'approved_success_dirs': tuple(ROOT / 'platform/state/evidence' / name for name in (
            'item-layout-20261105-005241',
            'item-api-query-20261105-045137',
            'item-query-ui-instruct-20261105-053626',
            'item-api-create-policy-repair-20261105-082420',
            'item-create-ui-20261105-141936',
            'item-api-update-20261105-143733',
            'item-update-ui-scoped-statements-20261105-151435',
            'item-api-delete-20261105-152816',
        )),
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-delete-ui-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Verified CRUD backend unchanged; browser deletion confirmation/cancel/target-only SQL persistence after unchanged query/create/update browser regression; all owned cleanup',
    },
    'toolbar-ui': {
        'acceptance': 'item-master-toolbar-ui-v1',
        'checks': ['frontend', 'framework'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': False,
        'context_profile': 'focused',
        'allowed': query_change,
        'allowed_new': frontend_new_source,
        'approved_success_dirs': tuple(ROOT / 'platform/state/evidence' / name for name in (
            'item-layout-20261105-005241',
            'item-api-query-20261105-045137',
            'item-query-ui-instruct-20261105-053626',
            'item-api-create-policy-repair-20261105-082420',
            'item-create-ui-20261105-141936',
            'item-api-update-20261105-143733',
            'item-update-ui-scoped-statements-20261105-151435',
            'item-api-delete-20261105-152816',
            'item-delete-ui-20261105-154343',
        )),
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-toolbar-ui-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Verified backend unchanged; real common-toolbar query/new/save, POST-to-PUT identity and collapsed draft validation after unchanged eighteen-case CRUD browser regression; all owned cleanup',
    },
    'api-delete': {
        'acceptance': 'item-master-api-delete-v1',
        'checks': ['backend'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': False,
        'context_profile': 'focused',
        'allowed': backend_existing_source,
        'allowed_new': backend_new_source,
        'approved_success_dirs': tuple(ROOT / 'platform/state/evidence' / name for name in (
            'item-layout-20261105-005241',
            'item-api-query-20261105-045137',
            'item-query-ui-instruct-20261105-053626',
            'item-api-create-policy-repair-20261105-082420',
            'item-create-ui-20261105-141936',
            'item-api-update-20261105-143733',
            'item-update-ui-scoped-statements-20261105-151435',
        )),
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-api-delete-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Fresh owned DELETE lifecycle database after unchanged GET/POST/PUT regression; preserve other rows and all frontend/migrations',
    },
    'api-update': {
        'acceptance': 'item-master-api-update-v1',
        'checks': ['backend'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': False,
        'context_profile': 'focused',
        'allowed': backend_existing_source,
        'allowed_new': backend_new_source,
        'approved_success_dirs': tuple(ROOT / 'platform/state/evidence' / name for name in (
            'item-layout-20261105-005241',
            'item-api-query-20261105-045137',
            'item-query-ui-instruct-20261105-053626',
            'item-api-create-policy-repair-20261105-082420',
            'item-create-ui-20261105-141936',
        )),
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-api-update-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Fresh owned database; preserve GET/POST and existing rows while testing real PUT, identity, validation, authentication and persistence; frontend unchanged',
    },
    'api-create': {
        'acceptance': 'item-master-api-create-v1',
        'checks': ['backend'],
        'max_calls': 32,
        'max_tokens': 8192,
        'wall_seconds': 1800,
        'thinking': True,
        'context_profile': 'focused',
        'allowed': backend_existing_source,
        'allowed_new': backend_new_source,
        'approved_success_dirs': tuple(ROOT / 'platform/state/evidence' / name for name in (
            'item-layout-20261105-005241',
            'item-api-query-20261105-045137',
            'item-query-ui-instruct-20261105-053626',
        )),
        'required_paths': [TARGET],
        'require_clean_start': False,
        'evidence_prefix': 'item-api-create-',
        'pointer': '/tmp/gemma-item-stage-current.txt',
        'database_policy': 'Fresh owned backend/database; real POST and SQL persistence with existing authentication/CSRF; preserve verified frontend and existing migrations',
    },
}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=STAGES)
    parser.add_argument('--model-config', help='Registered model configuration ID; defaults to the project selection')
    options = parser.parse_args()
    stage = dict(STAGES[options.stage])
    if options.model_config:
        stage['model_config'] = options.model_config
    sys.exit(main(stage))

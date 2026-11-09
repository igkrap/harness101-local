"""Validate the supported first milestone before any generation or DDL occurs."""
import hashlib
import json
import re


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[a-z][A-Za-z0-9_]{0,62}', value)) and value not in {'constructor', 'prototype', '__proto__'}


def validate(bundle):
    require(isinstance(bundle, dict) and set(bundle) == {'entity', 'operations', 'screen'}, 'Bundle requires entity, operations and screen')
    entity, operations, screen = bundle['entity'], bundle['operations'], bundle['screen']
    require(isinstance(entity, dict) and identifier(entity.get('table')) and entity['table'].startswith('spec_'), 'Prototype entities require a spec_ table name')
    require(isinstance(screen, dict) and re.fullmatch(r'[A-Z]{3}[0-9]{4}', screen.get('code', '')), 'Invalid screen code')
    require(screen.get('pattern') == 'query-edit', 'This milestone supports query-edit; other patterns need a registered generator')
    require(isinstance(screen.get('title'), str) and 0 < len(screen['title']) <= 80, 'Missing screen title')
    fields = entity.get('fields')
    require(isinstance(fields, list) and 3 <= len(fields) <= 24, 'Entity needs 3..24 fields')
    names, columns = set(), set()
    for field in fields:
        require(isinstance(field, dict) and identifier(field.get('name')) and identifier(field.get('column')), 'Invalid field identifier')
        require(field['name'] not in names and field['column'] not in columns, 'Duplicate field/column')
        names.add(field['name']); columns.add(field['column'])
        require(field.get('type') in ('text', 'email', 'integer', 'id', 'timestamp'), 'Unsupported prototype field type')
        require(isinstance(field.get('label'), str) and 0 < len(field['label']) <= 80, 'Invalid field label')
        require(type(field.get('required')) is bool, 'Field required flag must be explicit')
        if field['type'] in ('text', 'email'):
            require(type(field.get('maxLength')) is int and 1 <= field['maxLength'] <= 500, 'Text maxLength required')
        if field['type'] in ('integer', 'decimal'):
            require(type(field.get('min')) in (int, float), 'Numeric minimum required')
    by_name = {field['name']: field for field in fields}
    require(by_name.get('id', {}).get('type') == 'id' and by_name.get('createdAt', {}).get('type') == 'timestamp', 'Server-owned id/createdAt required')
    require(isinstance(operations, dict) and set(operations) == {'query', 'create', 'update'}, 'Explicit query/create/update contracts required')
    writable = {name for name, field in by_name.items() if field['type'] not in ('id', 'timestamp')}
    for kind, operation in operations.items():
        require(isinstance(operation, dict) and operation.get('kind') == kind, 'Operation kind mismatch')
        require(operation.get('permission') == 'workspace:admin', 'First milestone operations must use workspace:admin')
        require(operation.get('result') == [f['name'] for f in fields], 'Result contract must explicitly cover this entity')
        inputs = operation.get('inputs')
        require(isinstance(inputs, list) and len(inputs) <= 24, 'Invalid operation inputs')
        seen = set()
        for item in inputs:
            require(isinstance(item, dict) and identifier(item.get('name')), 'Invalid input name')
            require(item['name'] not in seen and item.get('field') in by_name, 'Duplicate input or missing field reference')
            seen.add(item['name'])
            require(type(item.get('required')) is bool, 'Operation input required flag must be explicit')
            if kind == 'query':
                require(item.get('operator') in ('eq', 'contains', 'gte'), 'Unsupported query operator')
                require(item.get('section') in ('primary', 'advanced'), 'Query visibility must be explicit')
                field_type = by_name[item['field']]['type']
                require(item['operator'] != 'contains' or field_type in ('text', 'email'), 'Contains needs text')
                require(item['operator'] != 'gte' or field_type in ('integer', 'decimal'), 'gte needs numeric field')
            else:
                require(item['name'] == item['field'] and item['field'] in writable, 'Write inputs must name writable fields')
                require(item['required'] == by_name[item['field']]['required'], 'Write required flags must match field constraints')
        if kind != 'query':
            require(seen == writable, 'All write fields must be defined; server-owned fields must be excluded')
            require(operation.get('transaction') == 'single-record', 'Transaction scope must be explicit')
    require(operations['create']['inputs'] == operations['update']['inputs'], 'Distinct write contracts supported next; first milestone uses matching create/update fields')
    tabs = screen.get('editorTabs')
    require(isinstance(tabs, list) and len(tabs) == 1 and set(tabs[0].get('fields', [])) == writable, 'First milestone needs one editor tab covering write inputs')
    require(identifier(tabs[0].get('id')) and isinstance(tabs[0].get('label'), str), 'Invalid editor tab')
    require(screen.get('columns') == [f['name'] for f in fields if f['type'] != 'timestamp'], 'Grid columns must be explicit')
    return bundle


def ddl(bundle):
    validate(bundle)
    types = {'id': 'bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY', 'timestamp': 'timestamptz NOT NULL DEFAULT now()',
             'integer': 'integer', 'decimal': 'numeric(18,2)'}
    declarations = []
    for field in bundle['entity']['fields']:
        kind = field['type']
        declaration = '"' + field['column'] + '" ' + (f"varchar({field['maxLength']})" if kind in ('text', 'email') else types[kind])
        if kind not in ('id', 'timestamp'):
            if field['required']:
                declaration += ' NOT NULL'
            if kind in ('integer', 'decimal'):
                declaration += ' CHECK ("' + field['column'] + '" >= ' + str(field['min']) + ')'
        declarations.append(declaration)
    return '-- Generated deterministically from specification ' + digest(bundle) + '\nCREATE TABLE "' + bundle['entity']['table'] + '" (\n  ' + ',\n  '.join(declarations) + '\n);\n'

"""Checks derived from a definition. Nobody writes scenarios: each thing a definition can say brings its own.

  entity            create -> appears in the list -> update -> delete -> gone
  required field    a blank value is refused
  optional fields   may all be left out
  number/date/code  a wrong kind of value is refused
  ref field         a missing target is refused; a target that is in use cannot be deleted, and can once it is free
  search field      filters the list
  screen            workspace, query panel, grid, editor, toolbar; every field is in the editor; required ones are marked and in the grid
  parts             numbering, lines (count limits), computed values and totals, number ranges, uniqueness, status start, each action and its refusal, locked statuses
  blocking rule     refused (with its message) while a row points here; allowed again once that row is gone

Everything runs against a trial copy of the definition (a draft the menus never show), and every row a
check creates is removed again, also when a check fails.
"""
import itertools
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / 'erp-harness'


import time as _time
# Values that must be unique stay unique across runs too (a row left by an interrupted run must not collide with the next one).
_serial = itertools.count(int(_time.time()) % 100000 * 100)


def _number(field, wanted):
    """A number of the wanted size, moved inside the field's allowed range."""
    low, high = field.get('min'), field.get('max')
    if low is not None and wanted < low:
        wanted = low
    if high is not None and wanted > high:
        wanted = high
    return int(wanted) if float(wanted).is_integer() else wanted


def sample(field, framework, made):
    """A value of the right kind for this field; for a ref, a freshly made row of the target (remembered in made)."""
    kind = field.get('type', 'text')
    if kind == 'number':
        return _number(field, 10 + (next(_serial) if field.get('unique') else 0))
    if kind == 'date':
        return '2026-01-15'
    if kind == 'time':
        return '09:30:00'
    if kind == 'yesno':
        return True
    if kind == 'code':
        codes = framework.codes(field['codeGroup'])
        return codes[0]['code'] if codes else None
    if kind == 'ref' and field['ref'].get('line'):
        return None                       # a line of another master: chosen once the record it must belong to is known (settle)
    if kind == 'ref':
        target = field['ref']['entity']
        definition = next(item['definition'] for item in framework.definitions() if item['key'] == target)
        body = {item['name']: sample(item, framework, made) for item in definition['fields'] if item.get('required') and not _computed(item)}
        if definition.get('lines') and definition['lines'].get('min', 1) > 0:      # it cannot exist without a line
            body['lines'] = [_line(definition['lines']['fields'], framework, made, 1)]
        body = fit(body, definition, framework, made)
        ready_masters(definition, body, framework, made)       # a target that draws on master data when it is registered needs that master first
        row = framework.ok('POST', f'/api/data/{target}', body)
        made.append((target, row['id']))
        return row['id']
    return f"{field['label']} 시험" + (str(next(_serial)) if field.get('unique') else '')


def _shift(value, by):
    """A date, a time or a number moved by some days / minutes / units."""
    if isinstance(value, str) and ':' in value:
        hour, minute = int(value[:2]), int(value[3:5])
        total = max(0, min(23 * 60 + 59, hour * 60 + minute + by))
        return f'{total // 60:02d}:{total % 60:02d}:00'
    if isinstance(value, str):
        import datetime
        return (datetime.date.fromisoformat(value) + datetime.timedelta(days=by)).isoformat()
    return value + by


def _units(body, in_lines):
    return (body.get('lines') or []) if in_lines else [body]


def _sets(definition):
    """Every table of lines of a definition as (name in the record, its part): the first as 'lines', then the further ones."""
    out = [('lines', definition['lines'])] if definition.get('lines') else []
    return out + [(more['name'], more) for more in definition.get('moreLines') or []]


def _holds(when, unit, above=None):
    """Whether a field's condition holds under these values (as the framework judges it)."""
    if not when:
        return False
    value = unit.get(when['field']) if when['field'] in unit else (above or {}).get(when['field'])
    text = '' if value is None else 'true' if value is True else 'false' if value is False else f'{value:g}' if isinstance(value, float) else str(value).strip()
    matches = text in when['is'] or (text == '' and 'false' in when['is'])
    return not matches if when.get('not') else matches


def _wanted(field, text):
    """A condition's value as a body carries it for that field."""
    kind = field.get('type', 'text')
    if kind == 'yesno':
        return text == 'true'
    if kind in ('number', 'ref'):
        try:
            return int(text) if float(text).is_integer() else float(text)
        except ValueError:
            return None
    return text or None


NONE = object()


def _unwanted(field, when, framework):
    """A value of the condition's field under which the condition does not hold (NONE when there is no such value to give)."""
    kind = field.get('type', 'text')
    if kind == 'yesno':
        return NONE if {'true', 'false'} <= set(when['is']) else 'true' not in when['is']
    if kind == 'code':
        return next((code['code'] for code in framework.codes(field['codeGroup']) if code['code'] not in when['is']), NONE)
    if kind == 'number':
        return next((value for value in (_number(field, 10), _number(field, 11), _number(field, 12)) if f'{value:g}' not in when['is']), NONE)
    if kind in ('text',):
        return '해당없음'
    return NONE


def _groups(body, definition):
    """The record and each of its lines as (fields, unit, the record above a line or None)."""
    out = [(definition.get('fields') or [], body, None)]
    for name, part in _sets(definition):
        out += [(part['fields'], line, body) for line in body.get(name) or []]
    return out


_line_use = {}


def ready_masters(definition, body, framework, made):
    """For a record whose registration expands master data (a work order and its BOM): a matching master valid on the day, made for the occasion."""
    for effect in definition.get('effects') or []:
        part = effect.get('expand')
        if not part or effect.get('on') != 'create':
            continue
        master = next(item['definition'] for item in framework.definitions() if item['key'] == part['from'])
        given = {field['name']: sample(field, framework, made) for field in master['fields'] if not _computed(field)}
        if master.get('lines'):
            given['lines'] = [_line(master['lines']['fields'], framework, made, 2)]
        for theirs, mine in part['match'].items():
            given[theirs] = body.get(mine)
        given = fit(given, master, framework, made)
        for theirs, mine in part['match'].items():
            given[theirs] = body.get(mine)
        if master.get('effective'):
            given[master['effective']['from']] = '2000-01-01'
            if master['effective'].get('to'):
                given[master['effective']['to']] = None
        code, row = framework.call('POST', f"/api/data/{part['from']}", given)
        if code == 201:
            made.append((part['from'], row['id']))


def sample_line(ref, owner, framework, made, index=None):
    """A line of another master that goes with `owner` (a step of this item's routing): the record of that master for the owner is
    used when there is one (a master like a routing exists once per item), else made for the occasion with a few lines. Each call
    takes the next line, so two lines of one sample point at different lines there."""
    target = next(item['definition'] for item in framework.definitions() if item['key'] == ref['entity'])
    found = []
    if ref.get('withinTarget') and owner is not None:
        found = [row for row in framework.ok('GET', f"/api/data/{ref['entity']}?{ref['withinTarget']}={owner}&_limit=5") if row.get(ref['withinTarget']) == owner]
    if found:
        row = framework.ok('GET', f"/api/data/{ref['entity']}/{found[0]['id']}")
    else:
        body = {field['name']: sample(field, framework, made) for field in target['fields'] if not _computed(field)}
        if ref.get('withinTarget') and owner is not None:
            body[ref['withinTarget']] = owner
        body['lines'] = [_line(target['lines']['fields'], framework, made, 2 + number) for number in range(min(3, target['lines'].get('max') or 3))]
        body = fit(body, target, framework, made)
        if ref.get('withinTarget') and owner is not None:
            body[ref['withinTarget']] = owner
        row = framework.ok('POST', f"/api/data/{ref['entity']}", body)
        made.append((ref['entity'], row['id']))
    lines = row.get('lines') or []
    if not lines:
        return None
    place = (ref['entity'], row['id'])
    at = _line_use.get(place, 0) if index is None else index
    _line_use[place] = at + 1
    return lines[at % len(lines)]['_line']


def settle(body, definition, framework, made):
    """Make a sample body agree with the definition's conditions (showWhen, requiredWhen, lockWhen), and give it the further
    tables of lines it cannot exist without. Each condition's field takes the first value asked for, so the fields that depend on
    it are there; a field that is still not there holds nothing (as the framework will store it); locks are kept from holding
    where that is free; what has become required is filled."""
    period = definition.get('effective')
    if period and not body.get('_period_kept'):              # each sample a period of its own, far from the others, so samples never overlap
        start = 2100 + next(_serial) % 800
        body[period['from']] = f'{start}-01-01'
        if period.get('to'):
            body[period['to']] = f'{start}-12-31'
    body.pop('_period_kept', None)
    for group in definition.get('uniqueBy') or []:          # each sample its own combination: a text or number field of it is made distinct
        fields_by = {field['name']: field for field in definition.get('fields') or []}
        for name in group:
            field = fields_by.get(name, {})
            if field.get('type', 'text') == 'text':
                body[name] = f"{field.get('label', name)} 시험{next(_serial)}"
                break
            if field.get('type') == 'number':
                body[name] = _number(field, next(_serial) % 100000 + 1)
                break
    for name, part in _sets(definition)[1:]:
        if part.get('min', 0) > 0 and not body.get(name):
            body[name] = [_line(part['fields'], framework, made, 2) for _ in range(part['min'])]
    header = {field['name']: field for field in definition.get('fields') or []}
    for fields, unit, above in _groups(body, definition):
        own, chosen = {field['name']: field for field in fields}, set()
        for field in fields:
            for part in ('showWhen', 'requiredWhen'):
                when = field.get(part)
                if when and when.get('not'):          # "is not": a sample value already holds it (anything but the listed values)
                    continue
                if when and when['field'] not in chosen and (when['field'] in own or above is None or not above.get('_settled', {}).get(when['field'])):
                    holder, target = (unit, own[when['field']]) if when['field'] in own else (above, header.get(when['field']))
                    if target is not None and not _holds(when, unit, above):
                        holder[when['field']] = _wanted(target, when['is'][0])
                    chosen.add(when['field'])
        for field in fields:
            when = field.get('lockWhen')
            if when and not when.get('not') and when['field'] not in chosen and when['field'] in own and _holds(when, unit, above):
                free = _unwanted(own[when['field']], when, framework)
                if free is not NONE:
                    unit[when['field']] = free
        if above is None:
            unit['_settled'] = {name: True for name in chosen}
    body.pop('_settled', None)
    for fields, unit, above in _groups(body, definition):      # lines of other masters, of the record this one goes with
        for field in fields:
            ref = field.get('ref') or {}
            if ref.get('line') and unit.get(field['name']) is None and (field.get('required') or True):
                owner = None
                if ref.get('within'):
                    owner = unit.get(ref['within']) if ref['within'] in unit else (above or {}).get(ref['within'])
                unit[field['name']] = sample_line(ref, owner, framework, made)
    for fields, unit, above in _groups(body, definition):
        for field in fields:
            if _computed(field):
                continue
            if field.get('showWhen') and not _holds(field['showWhen'], unit, above):
                unit[field['name']] = False if field.get('type') == 'yesno' else None
            elif unit.get(field['name']) is None and (field.get('required') or _holds(field.get('requiredWhen'), unit, above)) and field.get('type') != 'yesno':
                unit[field['name']] = sample(field, framework, made)
    return body


def _there(field, unit, above=None):
    """Whether the field is on the form under these values (a field with showWhen may not be)."""
    return not field.get('showWhen') or _holds(field['showWhen'], unit, above)


def fit(body, definition, framework, made, break_check=None):
    """Make a sample body obey the definition's own checks and limits (a sample of plain values would not: every date is
    the same day, and a limit allows nothing until the other entity holds a matching row). break_check: the one check to violate."""
    import datetime
    today = datetime.date.today().isoformat()
    settle(body, definition, framework, made)
    def obey():
        for check in definition.get('checks') or []:
            for unit in _units(body, check.get('lines')):
                right = today if check['right'] == 'today' else unit.get(check['right'])
                if right is None:
                    kinds = {field['name']: field.get('type') for field in definition['fields'] + (definition.get('lines') or {}).get('fields', [])}
                    right = unit[check['right']] = '09:30:00' if kinds.get(check['right']) == 'time' else '2026-01-15' if isinstance(unit.get(check['left']), str) or unit.get(check['left']) is None else 10
                keep = {'>': 1, '>=': 0, '<': -1, '<=': 0, '==': 0, '!=': 1}[check['op']]
                wrong = {'>': 0, '>=': -1, '<': 0, '<=': 1, '==': 1, '!=': 0}[check['op']]
                unit[check['left']] = _shift(right, wrong if check is break_check else keep)
    obey()
    line_names = {field['name'] for field in (definition.get('lines') or {}).get('fields', [])}
    known = {item['key']: item['definition'] for item in framework.definitions()} if definition.get('limits') else {}
    # A record may be limited by two stages at once (a result by its instruction and by the order behind it). The nearer stage is settled
    # first; the farther one is then the record that stage itself points at, so both speak of the same item and quantity.
    entities = [limit['entity'] for limit in definition.get('limits') or []]
    nearer = lambda limit: 0 if any(far['entity'] in entities for far in known.get(limit['entity'], {}).get('limits') or []) else 1
    settled = {}
    for limit in sorted(definition.get('limits') or [], key=nearer):
        other = known[limit['entity']]
        pairs = list(zip(limit['by'], limit['entityBy']))
        if limit.get('lines'):
            if not body.get('lines'):
                continue
            body['lines'] = body['lines'][:1]         # one line, so the whole allowance can go to it
        unit = body['lines'][0] if limit.get('lines') else body
        via = next((mine for mine, theirs in pairs if theirs == 'id'), None)
        holder = lambda name: unit if limit.get('lines') and name in line_names else body
        for stage, (stage_row, stage_unit) in settled.items():       # a nearer stage already chosen points at this one: follow it
            behind = next((item for item in known[stage].get('limits') or [] if item['entity'] == limit['entity'] and 'id' in item['entityBy']), None)
            if via and behind:
                pointer = behind['by'][behind['entityBy'].index('id')]
                found = stage_unit.get(pointer) if pointer in stage_unit else stage_row.get(pointer)
                if found:
                    holder(via)[via] = found
        if via and holder(via).get(via):
            row = framework.ok('GET', f"/api/data/{limit['entity']}/{holder(via)[via]}")
        else:                                           # nothing points at the other entity: make the row that gives the allowance
            given = {item['name']: sample(item, framework, made) for item in other['fields'] if item.get('required') and not _computed(item)}
            if other.get('lines') and (other['lines'].get('min', 1) > 0 or limit.get('entityLines')):
                given['lines'] = [_line(other['lines']['fields'], framework, made, 1)]
            row = framework.ok('POST', f"/api/data/{limit['entity']}", fit(given, other, framework, made))
            made.append((limit['entity'], row['id']))
        theirs_unit = (row.get('lines') or [{}])[0] if limit.get('entityLines') else row
        settled[limit['entity']] = (row, theirs_unit)
        value_of = lambda name: row['id'] if name == 'id' else theirs_unit.get(name) if name in theirs_unit else row.get(name)
        for mine, theirs in pairs:
            holder(mine)[mine] = value_of(theirs)
        unit[limit['field']] = value_of(limit['entityField']) or 0
    if definition.get('limits'):
        obey()          # a limit may have changed a number a check compares: the checks are made true again
    if (definition.get('stock') or {}).get('lot'):       # a lot number is only for items kept by lot: a plain sample leaves it empty
        for _, _, _, unit in _stock_units(body, definition):
            unit[definition['stock']['lot']] = None
    stock_ready(body, definition, framework)
    return body


def _stock_units(body, definition):
    """What a record moves, as (item, warehouse, quantity, the unit the quantity sits in) per line (or once, when the quantity is above the lines)."""
    part = definition.get('stock')
    if not part:
        return []
    line_names = {field['name'] for field in (definition.get('lines') or {}).get('fields', [])}
    units = (body.get('lines') or []) if part['quantity'] in line_names else [body]
    at = lambda unit, name: unit.get(name) if name in unit else body.get(name)
    return [(at(unit, part['item']), at(unit, part['warehouse']), at(unit, part['quantity']) or 0, unit) for unit in units]


def stock_of(framework, item, warehouse):
    rows = framework.ok('GET', f'/api/stock/balance?item={item}&warehouse={warehouse}')
    return float(rows[0]['quantity']) if rows else 0.0


def stock_ready(body, definition, framework, cost=100):
    """A sample of an issuing screen can only be stored when the stock is there: what it lacks is put in (as opening stock, at a known cost)."""
    part = definition.get('stock')
    if not part or part['direction'] in ('in', 'count'):
        return
    need = {}
    for item, warehouse, quantity, _ in _stock_units(body, definition):
        if item and warehouse and isinstance(quantity, (int, float)):
            need[(item, warehouse)] = need.get((item, warehouse), 0) + quantity
    for (item, warehouse), quantity in need.items():
        short = quantity - stock_of(framework, item, warehouse)
        if short > 0:
            framework.ok('POST', '/api/system/stock/adjust', {'itemEntity': part['itemEntity'], 'itemId': item, 'warehouseEntity': part['warehouseEntity'], 'warehouseId': warehouse, 'quantity': short, 'unitCost': cost})


def lot_checks(report, definition, framework, new_body, api):
    """Items kept by lot: a lot number typed when receiving names the lot; typed when issuing, only that lot is taken from; for an item
    kept by quantity only a lot number is refused. Tried on the sample's own item, switched to 'by lot' for the occasion."""
    part = definition['stock']
    if not part.get('lot'):
        return
    counting = part['direction'] == 'count'          # a count names the lot it counts: only the "not for a quantity-only item" rule applies
    known = {item['key']: item['definition'] for item in framework.definitions()}
    mode = next((field for field in known[part['itemEntity']]['fields'] if field.get('codeGroup') == 'STOCK_TRACKING'), None)
    meta = ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt', '_names', '_files', '_stock')
    made = []

    def remove():
        for record in reversed(made):
            if framework.call('DELETE', f'{api}/{record}')[0] == 409:
                framework.call('DELETE', f'{api}/{record}?force=true')
        made.clear()
    try:
        body = new_body()
        every = _stock_units(body, definition)
        item, warehouse, quantity, unit = next(one for one in every if one[0] and one[1] and one[2])
        place = next(index for index, one in enumerate(every) if one[3] is unit) + 1        # the line the lot is typed on: only its movements are looked at
        unit[part['lot']] = 'L-NONE-1'
        code, answer = framework.call('POST', api, body)
        if code == 201:
            made.append(answer['id'])
        report.add('LOT: 수량만 관리하는 품목에 LOT 번호를 적으면 거절되고 이유가 나온다', code == 400 and 'LOT' in str((answer or {}).get('detail')), f'{code} {answer}')
        remove()
        if not mode or counting:
            return
        record = framework.ok('GET', f"/api/data/{part['itemEntity']}/{item}")
        framework.ok('PUT', f"/api/data/{part['itemEntity']}/{item}", dict({name: value for name, value in record.items() if name not in meta}, **{mode['name']: 'LOT'}))
        number = f'L-{next(_serial)}'
        if part['direction'] == 'in':
            unit[part['lot']] = number
            code, row = framework.call('POST', api, body)
            if code == 201:
                made.append(row['id'])
            lots = [line.get('lot') for line in (row.get('_stock') or []) if line.get('line') == place] if code == 201 else []
            report.add('LOT: LOT 관리 품목은 입고할 때 적은 번호가 LOT 번호가 된다', code == 201 and number in lots, f'{code} {lots or row}')
        else:
            have = stock_of(framework, item, warehouse)        # what the sample put in sits in lots with numbers of their own
            unit[part['lot']] = number
            code, answer = framework.call('POST', api, body)
            if code == 201:
                made.append(answer['id'])
            report.add('LOT: 없는 LOT 번호를 지정해 꺼내면 (다른 LOT 에 재고가 있어도) 거절된다', code == 400 and have >= quantity and 'LOT' in str((answer or {}).get('detail')), f'{code} 현재고 {have:g} {answer}')
            there = framework.ok('GET', f'/api/stock/lots?item={item}&warehouse={warehouse}')
            if there:
                unit[part['lot']] = there[0]['lot']
                code, row = framework.call('POST', api, body)
                if code == 201:
                    made.append(row['id'])
                lots = {line.get('lot') for line in (row.get('_stock') or []) if line.get('line') == place} if code == 201 else set()
                report.add('LOT: 있는 LOT 번호를 지정하면 그 LOT 에서만 꺼낸다', code == 201 and lots == {there[0]['lot']} or (code == 400 and float(there[0]['remaining']) < quantity), f'{code} {lots or row}')
    finally:
        remove()


def line_ref_checks(report, definition, framework, made, new_body, post, api):
    """Layer 3: a field that points at a line of another master. A line of a record that does not go with this one is refused; so is a line that is not there."""
    for where, fields in (('', definition['fields']), ('줄의 ', (definition.get('lines') or {}).get('fields', []))):
        for field in [item for item in fields if (item.get('ref') or {}).get('line')]:
            ref = field['ref']
            body = new_body()
            unit = (body.get('lines') or [None])[0] if where else body
            if unit is None:
                continue
            if ref.get('within'):
                other = sample({'type': 'ref', 'ref': {'entity': next((one['ref']['entity'] for one in definition['fields'] + (definition.get('lines') or {}).get('fields', []) if one['name'] == ref['within'] and one.get('ref')), ''), 'label': ''}}, framework, made) \
                    if any(one['name'] == ref['within'] and one.get('ref') for one in definition['fields'] + (definition.get('lines') or {}).get('fields', [])) else f'다른값{next(_serial)}'
                unit[field['name']] = sample_line(ref, other, framework, made)
                code, answer = post(body)
                report.add(f"{where}{field['label']}: 이 자료와 같은 {ref['within']} 이(가) 아닌 건의 줄을 고르면 거절된다", code == 400 and '것이 아닙니다' in str((answer or {}).get('detail')), f'{code} {answer}')
            body = new_body()
            unit = (body.get('lines') or [None])[0] if where else body
            unit[field['name']] = 999999999
            code, answer = post(body)
            report.add(f"{where}{field['label']}: 없는 줄을 가리키면 거절된다", code == 400, f'{code} {answer}')


def effective_checks(report, definition, framework, made, new_body, post, api):
    """Master data valid for a period: the same kind may not overlap in time; an end before the start is refused; periods side by side are fine."""
    period = definition.get('effective')
    if not period:
        return
    first = new_body()
    first[period['from']] = '2031-01-01'
    if period.get('to'):
        first[period['to']] = '2031-06-30'
    code, row = post(first)
    if not report.add('적용 기간: 기간이 있는 자료를 저장한다', code == 201, f'{code} {row}'):
        return
    def same(day_from, day_to=None):
        body = new_body()
        body.update({name: first.get(name) for name in period.get('by') or []})
        body[period['from']] = day_from
        if period.get('to'):
            body[period['to']] = day_to
        return body
    code, answer = post(same('2031-03-01', '2031-12-31'))
    report.add('적용 기간: 같은 기준의 기간이 겹치면 거절된다', code == 400 and '겹칩니다' in str((answer or {}).get('detail')), f'{code} {answer}')
    if period.get('to'):
        code, answer = post(same('2031-07-01', '2031-12-31'))
        report.add('적용 기간: 앞 기간이 끝난 다음 날부터는 저장된다', code == 201, f'{code} {answer}')
        code, answer = post(same('2032-05-01', '2032-04-01'))
        report.add('적용 기간: 종료일이 시작일보다 앞서면 거절된다', code == 400, f'{code} {answer}')


def layer_checks(report, definition, framework, made, new_body, post, api):
    """Master data that combines other master data: a combination taken twice, a value twice in one record's lines, a part that is the item
    itself or leads back to it - each refused with its reason; the same records apart are stored."""
    for group in definition.get('uniqueBy') or []:
        first = new_body()
        code, row = post(first)
        if code != 201:
            report.add(f"조합 열쇠 {'·'.join(group)}: 시험할 자료를 저장한다", False, f'{code} {row}')
            continue
        again = new_body()
        again.update({name: first.get(name) for name in group})
        code, answer = post(again)
        report.add(f"조합 열쇠: {'·'.join(group)} 이(가) 같은 자료는 두 번 저장되지 않는다", code == 400 and '이미 있습니다' in str((answer or {}).get('detail')), f'{code} {answer}')
    for field in [item for item in (definition.get('lines') or {}).get('fields', []) if item.get('unique')]:
        body = new_body()
        if not body.get('lines'):
            continue
        twice = dict(body['lines'][0])
        body['lines'] = [body['lines'][0], twice] + body['lines'][1:]
        code, answer = post(body)
        report.add(f"줄의 {field['label']}: 한 건 안에서 같은 값을 두 줄로 넣으면 거절된다", code == 400 and '겹칩니다' in str((answer or {}).get('detail')), f'{code} {answer}')
    if definition.get('lines') and (definition.get('uniqueBy') or definition.get('noCycle') or any(item.get('unique') for item in definition['lines']['fields'])):
        body = new_body()
        code, row = post(body)
        if code == 201 and row.get('lines'):
            again = {name: value for name, value in row.items() if name not in ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt', '_names', '_files', '_stock')}
            ids = [line['_line'] for line in row['lines']]
            code2, after = framework.call('PUT', f"{api}/{row['id']}", again)
            report.add('기준 정보의 줄은 고쳐 저장해도 같은 줄로 남는다 (다른 기준 정보가 그 줄을 가리킬 수 있도록)', code2 == 200 and [line.get('_line') for line in after.get('lines', [])] == ids, f'{code2} {ids} → {[line.get("_line") for line in (after or {}).get("lines", [])] if isinstance(after, dict) else after}')
    cycle = definition.get('noCycle')
    if cycle:
        flat = any(field['name'] == cycle['child'] for field in definition['fields'])      # one pair per record (a BOM of parent-part pairs)
        holder = (lambda body: body) if flat else (lambda body: (body.get('lines') or [None])[0])
        body = new_body()
        if holder(body) is not None:
            holder(body)[cycle['child']] = body.get(cycle['parent'])
            code, answer = post(body)
            report.add('순환 금지: 하위에 상위 자신을 넣으면 거절된다', code == 400 and '자신' in str((answer or {}).get('detail')), f'{code} {answer}')
            upper = new_body()
            code, row = post(upper)               # A holds B ...
            if code == 201:
                back = new_body()                 # ... so B may not hold A
                back[cycle['parent']] = holder(upper)[cycle['child']]
                holder(back)[cycle['child']] = upper[cycle['parent']]
                code, answer = post(back)
                report.add('순환 금지: 다른 건을 거쳐 다시 상위로 돌아오면 거절된다 (A 의 하위에 B, B 의 하위에 A)', code == 400 and '순환' in str((answer or {}).get('detail')), f'{code} {answer}')
                deeper = new_body()               # a part of a part is fine as long as it does not come back
                deeper[cycle['parent']] = holder(upper)[cycle['child']]
                code, answer = post(deeper)
                report.add('순환 금지: 하위의 하위를 등록하는 것(다단계 구조)은 된다', code == 201, f'{code} {answer}')

def stock_checks(report, definition, framework, new_body, post, api):
    """A screen that moves stock: receiving makes lots at the line's cost and the stock goes up; issuing takes from the oldest lots at their cost,
    the stock goes down, and more than there is is refused; deleting the record takes its movement back."""
    part = definition.get('stock')
    if not part:
        return
    body = new_body()
    units = [unit for unit in _stock_units(body, definition) if unit[0] and unit[1] and unit[2]]
    if not units:
        return
    item, warehouse = units[0][0], units[0][1]
    moved = sum(quantity for one, house, quantity, _ in units if (one, house) == (item, warehouse))
    before = stock_of(framework, item, warehouse)
    code, row = post(body)
    if not report.add('재고: 자료가 저장된다', code == 201, f'{code} {row}'):
        return
    after, lines = stock_of(framework, item, warehouse), row.get('_stock') or []
    if part['direction'] == 'count':
        report.add(f'재고 실사: 저장하면 그 창고의 장부가 센 수량({moved:g})이 된다', abs(after - moved) < 1e-9, f'{before:g} → {after:g}')
        recount = {name: value for name, value in body.items() if name not in ('lines',)}          # the same item and warehouse, counted again
        for field in definition['fields']:
            if field.get('type') == 'serial' or _computed(field):
                recount.pop(field['name'], None)
        unit = recount if part['quantity'] in recount else None
        if unit is None:
            recount['lines'] = [dict(units[0][3])]
            unit = recount['lines'][0]
        unit[part['quantity']] = max(moved - 1, 0)
        code, again = post(recount)
        report.add(f'재고 실사: 다시 세어 줄면({max(moved - 1, 0):g}) 장부도 줄고 차이가 수불에 남는다', code == 201 and abs(stock_of(framework, item, warehouse) - max(moved - 1, 0)) < 1e-9
                   and any(line['direction'] == 'OUT' for line in again.get('_stock') or []), f'{code} {stock_of(framework, item, warehouse):g} {(again or {}).get("_stock") if isinstance(again, dict) else again}')
        if code == 201:
            framework.call('DELETE', f"{api}/{again['id']}")
        lines = []
    elif part['direction'] == 'in':
        report.add(f'재고: 등록하면 그 창고의 재고가 수량만큼({moved:g}) 늘어난다', abs(after - before - moved) < 1e-9, f'{before:g} → {after:g}')
        cost = units[0][3].get(part['unitCost']) if part.get('unitCost') else 0
        report.add('재고: 줄마다 LOT 가 생기고 그 줄의 단가가 LOT 단가가 된다', len(lines) == len(_stock_units(body, definition)) and all(line.get('lot') for line in lines) and float(lines[0]['unitCost']) == float(cost or 0), f'{lines[:2]}')
    else:
        report.add(f"재고: 등록하면 {'보내는' if part['direction'] == 'move' else '그'} 창고의 재고가 수량만큼({moved:g}) 줄어든다", abs(before - after - moved) < 1e-9, f'{before:g} → {after:g}')
        if part['direction'] == 'move':
            there = units[0][3].get(part['toWarehouse']) if part['toWarehouse'] in units[0][3] else body.get(part['toWarehouse'])
            arrived = [line for line in lines if line['direction'] == 'IN']
            report.add(f'재고: 받는 창고의 재고가 그만큼({moved:g}) 늘어나고 LOT 번호와 단가가 따라간다', abs(stock_of(framework, item, there) - moved) < 1e-9
                       and sorted((line['lot'], float(line['unitCost'])) for line in arrived) == sorted((line['lot'], float(line['unitCost'])) for line in lines if line['direction'] == 'OUT'), f'{stock_of(framework, item, there):g} {lines[:4]}')
            lines = [line for line in lines if line['direction'] == 'OUT']
            same = new_body()
            holder = (same.get('lines') or [same])[0] if part['toWarehouse'] in ((same.get('lines') or [{}])[0]) else same
            source = (same.get('lines') or [same])[0] if part['warehouse'] in ((same.get('lines') or [{}])[0]) else same
            holder[part['toWarehouse']] = source[part['warehouse']]
            code, answer = framework.call('POST', api, same)
            report.add('재고: 보내는 창고와 받는 창고가 같으면 거절된다', code == 400, f'{code} {answer}')
            if code == 201:
                framework.call('DELETE', f"{api}/{answer['id']}?force=true")
        report.add('재고: 꺼낸 LOT 와 그 단가로 원가가 잡힌다 (수량 × LOT 단가)', bool(lines) and all(abs(float(line['amount']) - float(line['quantity']) * float(line['unitCost'])) < 1e-6 for line in lines)
                   and abs(sum(float(line['quantity']) for line in lines if line['line'] == 1) - (units[0][2])) < 1e-9, f'{lines[:3]}')
        short = new_body()
        for one, house, quantity, _ in [unit for unit in _stock_units(short, definition) if unit[0] and unit[1]]:
            have = stock_of(framework, one, house)
            if have > 0:
                framework.ok('POST', '/api/system/stock/adjust', {'itemEntity': part['itemEntity'], 'itemId': one, 'warehouseEntity': part['warehouseEntity'], 'warehouseId': house, 'quantity': -have})
        code, answer = framework.call('POST', api, short)
        report.add('재고: 재고가 모자라면 저장이 거절되고 이유가 나온다', code == 400 and '재고' in str((answer or {}).get('detail')), f'{code} {answer}')
        if code == 201:
            framework.call('DELETE', f"{api}/{answer['id']}?force=true")
    lot_checks(report, definition, framework, new_body, api)
    code, _ = framework.call('DELETE', f"{api}/{row['id']}")
    if code == 409:
        code, _ = framework.call('DELETE', f"{api}/{row['id']}?force=true")
    back = stock_of(framework, item, warehouse)
    report.add('재고: 자료를 지우면 움직인 재고가 되돌아간다', code == 204 and abs(back - before) < 1e-9, f'{code} / {before:g} → {after:g} → {back:g}')


def closing_checks(report, definition, framework, new_body, post, api):
    """수불 마감: no stock moves on a day of a closed month, a record whose stock moved in it stays as it is, and opening it again lets it go.
    Months someone really closed are only read; otherwise a month long past (2000-01, nothing real in it) is closed for the check and opened again."""
    part = definition.get('stock')
    if not part or not part.get('date'):
        return

    def dated(body, day):
        if part['date'] in body or not body.get('lines'):
            body[part['date']] = day
        else:
            for line in body['lines']:
                line[part['date']] = day
        return body

    def said(answer):
        return '마감' in str((answer or {}).get('detail'))
    through = framework.ok('GET', '/api/stock-closings').get('through')
    if through:
        code, answer = post(dated(new_body(), through + '-01'))
        report.add(f'수불 마감: 마감된 달({through}) 날짜로는 재고가 움직이지 않는다 (거절되고 이유가 나온다)', code == 409 and said(answer), f'{code} {answer}')
        return
    day, month, kept = '2000-01-15', '2000-01', None
    if part['direction'] == 'in':
        code, kept = post(dated(new_body(), day))
        if not report.add('수불 마감: 지난 달 날짜로 입고가 저장된다 (마감 전)', code == 201, f'{code} {kept}'):
            return
    framework.ok('POST', '/api/stock-closings', {'period': month, 'note': '검사 중 잠깐 마감'})
    try:
        code, answer = post(dated(new_body(), day))
        report.add(f'수불 마감: 마감된 달({month}) 날짜로는 재고가 움직이지 않는다 (거절되고 이유가 나온다)', code == 409 and said(answer), f'{code} {answer}')
        if kept:
            meta = ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt', '_names', '_files', '_stock')
            record = framework.ok('GET', f"{api}/{kept['id']}")
            changed, removed = framework.call('PUT', f"{api}/{kept['id']}", {name: value for name, value in record.items() if name not in meta}), framework.call('DELETE', f"{api}/{kept['id']}")
            report.add('수불 마감: 마감된 달에 재고가 움직인 자료는 고칠 수도 지울 수도 없다', changed[0] == 409 and said(changed[1]) and removed[0] == 409 and said(removed[1]), f'{changed} {removed}')
    finally:
        framework.call('DELETE', f'/api/stock-closings/{month}')
    if kept:
        code, answer = framework.call('DELETE', f"{api}/{kept['id']}")
        report.add('수불 마감: 다시 열면 그 자료를 지울 수 있다', code == 204, f'{code} {answer}')


def _computed(field):
    return bool(field.get('formula') or field.get('sum') or field.get('type') == 'serial')


LEFTOVER = []


def sweep(framework, made):
    """Delete the sample rows, newest first. Returns the ones that could not be deleted yet (a row a locked
    trial document still points at goes once the trial definition is removed)."""
    left = []
    for entity, record in reversed(made):
        code, _ = framework.call('DELETE', f'/api/data/{entity}/{record}')
        if code == 409:      # locked, or held by a rule: the checks' own rows may be removed all the same (what others point at still may not)
            code, _ = framework.call('DELETE', f'/api/data/{entity}/{record}?force=true')
        if code not in (204, 404):
            left.append((entity, record))
        else:                # the platform's records leave no trace in the system's own history (platform and system kept apart)
            framework.call('DELETE', f'/api/system/history?entity={entity}&id={record}')
    left.reverse()
    framework.call('DELETE', '/api/system/stock/orphans')      # stock put in for sample items that are gone again
    LEFTOVER.extend(left)      # the run sweeps these once more after the trial definition is gone
    return left


def high_water(framework):
    """The newest record id there is (ids run across all entities), taken before a run makes anything."""
    top = 0
    for item in framework.definitions():
        if item['definition'].get('fields'):
            code, rows = framework.call('GET', f"/api/data/{item['key']}")
            if code == 200 and rows:
                top = max(top, max(row['id'] for row in rows))
    return top


def clear_since(framework, mark, by):
    """Remove every record newer than the mark that this account made: the checks' own samples, and whatever followed
    from them by itself (an effect that made an order out of a sample quotation). Newest first, forced where locked."""
    left = []
    for _ in range(3):
        found = []
        for item in framework.definitions():
            if item['definition'].get('fields'):
                code, rows = framework.call('GET', f"/api/data/{item['key']}")
                found += [(row['id'], item['key']) for row in (rows if code == 200 else []) if row['id'] > mark and row.get('createdBy') == by]
        if not found:
            return []
        left = []
        for record, entity in sorted(found, reverse=True):
            code, _ = framework.call('DELETE', f'/api/data/{entity}/{record}?force=true')
            if code in (204, 404):
                framework.call('DELETE', f'/api/system/history?entity={entity}&id={record}')
            if code not in (204, 404):
                left.append((entity, record))
    return left


class Report:
    def __init__(self):
        self.results = []
        self.leftover = []

    def add(self, description, passed, detail=''):
        self.results.append({'description': description, 'passed': bool(passed), 'detail': '' if passed else str(detail)[:400]})
        return bool(passed)

    @property
    def passed(self):
        return all(result['passed'] for result in self.results)


def _calc(formula, values):
    """The framework's formula language, evaluated here independently (only numbers, names, + - * / and parentheses)."""
    import re
    if not re.fullmatch(r'[A-Za-z0-9+\-*/(). ]+', formula):
        raise ValueError('formula: ' + formula)
    return eval(formula, {'__builtins__': {}}, dict(values))   # noqa: S307 - characters are restricted above


def _line(fields, framework, made, quantity):
    """One line with sample values; number fields get distinct, easy numbers so sums and products are telling."""
    body, number = {}, quantity
    for field in fields:
        if field.get('formula'):
            continue
        if field.get('type') == 'number':
            body[field['name']] = _number(field, number)
            number = number * 100 + 50     # e.g. quantity 3 -> price 350
        else:
            body[field['name']] = sample(field, framework, made)
    return body


def conditions(report, definition, framework, made, new_body, post, api):
    """Fields that depend on another field: there only when, required only when, locked when - each tried both ways where a value for the other way exists."""
    header = {field['name']: field for field in definition.get('fields') or []}

    def unit_of(body, table):
        return body if table is None else (body.get(table) or [None])[0]
    for table, part_label, fields in [(None, '', definition.get('fields') or [])] + [(name, part['label'] + ' 줄의 ', part['fields']) for name, part in _sets(definition)]:
        own = {field['name']: field for field in fields}
        for field in fields:
            for part in ('showWhen', 'requiredWhen', 'lockWhen'):
                when = field.get(part)
                target = when and (own.get(when['field']) or header.get(when['field']))
                if not target:
                    continue
                in_own = when['field'] in own

                def body_with(value):
                    """A sample whose condition field holds this value (the rest settled again around it), or None when there is no line to try on."""
                    body = new_body()
                    unit = unit_of(body, table)
                    if unit is None:
                        return None, None
                    (unit if in_own else body)[when['field']] = value
                    for fields2, unit2, above2 in _groups(body, definition):      # what the new value hides is emptied, what it asks for is filled
                        for other in fields2:
                            if _computed(other) or other is field:
                                continue
                            if other.get('showWhen') and not _holds(other['showWhen'], unit2, above2):
                                unit2[other['name']] = False if other.get('type') == 'yesno' else None
                            elif unit2.get(other['name']) is None and other.get('type') != 'yesno' and (other.get('required') or _holds(other.get('requiredWhen'), unit2, above2)):
                                unit2[other['name']] = sample(other, framework, made)
                    return body, unit
                if when.get('not'):                   # holds for anything but the listed values
                    other = _unwanted(target, when, framework)
                    on = sample(target, framework, made) if other is NONE else other
                    off = _wanted(target, when['is'][0])
                    if off is None and target.get('required'):
                        off = NONE               # the other way would leave a required field empty: not tried
                else:
                    on, off = _wanted(target, when['is'][0]), _unwanted(target, when, framework)
                words = f"{target['label']} 이(가) {'·'.join(when['is']) or '비어 있음'}"
                value = sample(field, framework, made) if field.get('type') != 'ref' else None
                if part == 'showWhen' and off is not NONE and value is not None and not (target.get('required') and off is None):
                    body, unit = body_with(off)
                    if body is not None:
                        unit[field['name']] = value
                        code, row = post(body)
                        stored = unit_of(row, table) if code == 201 else {}
                        report.add(f"조건: {part_label}{field['label']} 은(는) {words} 아닐 때는 없는 항목이라, 보내도 비워져 저장된다", code == 201 and (stored or {}).get(field['name']) in (None, False), f'{code} {row}')
                if part == 'requiredWhen':
                    body, unit = body_with(on)
                    if body is not None and _there(field, unit, body if table else None):
                        unit[field['name']] = None
                        code, answer = post(body)
                        report.add(f"조건: {part_label}{field['label']} 은(는) {words} 일 때 비우면 거절된다", code == 400, f'{code} {answer}')
                    if off is not NONE:
                        body, unit = body_with(off)
                        if body is not None:
                            unit[field['name']] = None
                            code, answer = post(body)
                            report.add(f"조건: {part_label}{field['label']} 은(는) {words} 아닐 때는 비워도 저장된다", code == 201, f'{code} {answer}')
                if part == 'lockWhen' and table is None and field.get('type') in ('text', 'number', 'date', 'time', 'memo', None):
                    body, unit = body_with(on)
                    if body is None or not _there(field, unit) or unit.get(field['name']) is None:
                        continue
                    code, row = post(body)
                    if code != 201:
                        report.add(f"조건: {field['label']} 이(가) 잠기는 값({words})으로도 새로 등록된다", False, f'{code} {row}')
                        continue
                    again = json.loads(json.dumps(body))
                    again[field['name']] = (str(body[field['name']]) + '2') if field.get('type', 'text') in ('text', 'memo') else _shift(body[field['name']], -1 if field.get('max') is not None else 1)
                    code, after = framework.call('PUT', f"{api}/{row['id']}", again)
                    report.add(f"조건: {field['label']} 은(는) {words} 일 때 잠겨, 고쳐 보내도 저장된 값이 남는다", code == 200 and after.get(field['name']) == row.get(field['name']), f"{code} 보낸 값 {again[field['name']]}, 남은 값 {(after or {}).get(field['name']) if isinstance(after, dict) else after}")


def record_checks(key, definition, framework):
    """Every data rule the definition states, tried against /api/data/<key>. A screen is its parts, and so are its
    checks: fields always; numbering, lines, computed values, ranges, uniqueness, status only where the definition has them."""
    report, made, api = Report(), [], f'/api/data/{key}'
    fields, lines, status = definition['fields'], definition.get('lines'), definition.get('status')
    line_fields = lines['fields'] if lines else []
    low, high = (lines.get('min', 1), lines.get('max')) if lines else (0, None)
    plain = [field for field in fields if not _computed(field)]
    usual = 0 if not lines else max(low, 1) if high == 1 else max(low, 2) if high is None else min(max(low, 2), high)
    more = _sets(definition)[1:]

    def new_body(count=None):
        body = {field['name']: sample(field, framework, made) for field in plain}
        if lines:
            body['lines'] = [_line(line_fields, framework, made, 3 - index % 2) for index in range(usual if count is None else count)]
        for name, part in more:
            body[name] = [_line(part['fields'], framework, made, 2 + index) for index in range(min(max(part.get('min', 0), 2), part.get('max') or 2))]
        return fit(body, definition, framework, made) if count is None else settle(body, definition, framework, made)      # the line-count tests keep their count

    def post(body):
        code, answer = framework.call('POST', api, body)
        if code == 201:
            made.append((key, answer['id']))
        return code, answer

    def refused(description, body, expected=400):
        code, answer = post(body)
        report.add(description, code == expected, f'{code} {answer}')
    try:
        body = new_body()
        sent = json.loads(json.dumps(body))
        for name, part in _sets(definition):               # values the server must ignore and work out itself
            for line in sent.get(name, []):
                for field in part['fields']:
                    if field.get('formula'):
                        line[field['name']] = 1
        code, row = post(sent)
        if not report.add('등록: 항목' + ('과 줄 표' if lines else '') + '를 채워 저장된다', code == 201, f'{code} {row}'):
            return report
        wrong = [field['label'] for field in plain if body[field['name']] is not None and row.get(field['name']) != body[field['name']]]
        report.add('저장 확인: 보낸 값이 항목마다 그대로 돌아온다', not wrong, f'다르게 저장된 항목: {wrong}')
        for field in [item for item in line_fields if item.get('formula')]:
            expected = [_calc(field['formula'], line) for line in body['lines']]
            got = [line.get(field['name']) for line in row.get('lines', [])]
            report.add(f"계산: 줄의 {field['label']} = {field['formula']} (보낸 값은 무시된다)", got == expected, f'기대 {expected}, 실제 {got}')
        for field in [item for item in fields if item.get('sum')]:
            table, column = field['sum'].split('.', 1) if '.' in field['sum'] else ('lines', field['sum'])
            expected = sum(line.get(column) or 0 for line in row.get(table, []))
            report.add(f"합계: {field['label']} 은(는) {'줄' if table == 'lines' else dict(more)[table]['label']}의 {column} 을(를) 더한 값이다", row.get(field['name']) == expected, f"기대 {expected}, 실제 {row.get(field['name'])}")
        for name, part in more:
            got, wanted_lines = row.get(name) or [], body.get(name) or []
            typed = [field for field in part['fields'] if not _computed(field)]
            same = len(got) == len(wanted_lines) and all(mine.get(field['name']) == theirs.get(field['name']) for mine, theirs in zip(wanted_lines, got) for field in typed if mine.get(field['name']) is not None)
            report.add(f"줄 표 {part['label']}: 보낸 줄이 그대로 저장된다 ({len(wanted_lines)}줄)", same, f'보낸 것 {wanted_lines}, 저장된 것 {got}')
            for field in [item for item in part['fields'] if item.get('formula')]:
                expected = [_calc(field['formula'], line) for line in wanted_lines]
                report.add(f"계산: {part['label']} 줄의 {field['label']} = {field['formula']}", [line.get(field['name']) for line in got] == expected, f"기대 {expected}, 실제 {[line.get(field['name']) for line in got]}")
            if part.get('min', 0) > 0:
                short = new_body()
                short[name] = short[name][:part['min'] - 1]
                refused(f"줄 표 {part['label']}: {part['min']}줄보다 적으면 거절된다", short)
            if part.get('max') is not None:
                long = new_body()
                long[name] = [dict(long[name][0]) for _ in range(part['max'] + 1)] if long[name] else [_line(part['fields'], framework, made, 2) for _ in range(part['max'] + 1)]
                refused(f"줄 표 {part['label']}: {part['max']}줄보다 많으면 거절된다", long)
        for field in [item for item in fields if item.get('formula')]:
            expected = _calc(field['formula'], {name: value for name, value in row.items() if isinstance(value, (int, float))})
            report.add(f"계산: {field['label']} = {field['formula']}", row.get(field['name']) == expected, f"기대 {expected}, 실제 {row.get(field['name'])}")
        for field in [item for item in fields if item.get('type') == 'serial']:
            code2, second = post(new_body())
            first, following = str(row.get(field['name'])), str(second.get(field['name'])) if code2 == 201 else ''
            report.add(f"채번: {field['label']} 이(가) {field['prefix']}- 로 시작하고 건마다 다르게 이어진다",
                       first.startswith(field['prefix'] + '-') and following.startswith(field['prefix'] + '-') and following > first, f'{first}, {following}')
        code, rows = framework.call('GET', api)
        report.add('조회: 목록에 방금 등록한 자료가 있다', code == 200 and any(item['id'] == row['id'] for item in rows), f'{code}')
        for field in [item for item in plain if item.get('search') and item.get('type', 'text') == 'text']:
            _, hit = framework.call('GET', f"{api}?{field['name']}={body[field['name']]}")
            _, miss = framework.call('GET', f"{api}?{field['name']}=없는값zzqq")
            report.add(f"조회 조건 {field['label']}: 맞는 값은 찾고 없는 값은 못 찾는다", any(item['id'] == row['id'] for item in hit or []) and not miss, f'hit={len(hit or [])} miss={len(miss or [])}')
        for field in [item for item in plain if item['required']]:
            broken = new_body()
            if _there(field, broken):            # a field that is not there under the sample's values is asked for nothing
                refused(f"필수 항목 {field['label']}: 비우면 거절된다", dict(broken, **{field['name']: '' if field.get('type', 'text') == 'text' else None}))
        if usual:
            for field in [item for item in line_fields if item['required']]:
                broken = new_body()
                if _there(field, broken['lines'][0], broken):
                    broken['lines'][0][field['name']] = None
                    refused(f"줄의 필수 항목 {field['label']}: 비우면 거절된다", broken)
        conditions(report, definition, framework, made, new_body, post, api)
        stock_checks(report, definition, framework, new_body, post, api)
        closing_checks(report, definition, framework, new_body, post, api)
        layer_checks(report, definition, framework, made, new_body, post, api)
        effective_checks(report, definition, framework, made, new_body, post, api)
        line_ref_checks(report, definition, framework, made, new_body, post, api)
        minimal = {field['name']: value for field, value in ((field, sample(field, framework, made)) for field in plain if field['required'])}
        if lines and low > 0:
            minimal['lines'] = [{field['name']: value for field, value in ((field, _line([field], framework, made, 2)[field['name']]) for field in line_fields if field['required'])} for _ in range(low)]
        code, answer = post(fit(minimal, definition, framework, made))
        report.add('선택 항목은 모두 비워도 저장된다', code == 201, f'{code} {answer}')
        wrong_values = {'number': '열 개', 'date': '1월 15일', 'time': '아침 일찍', 'code': '없는코드zz', 'ref': 999999999}
        for field in [item for item in plain if item.get('type', 'text') in wrong_values]:
            broken = new_body()
            if _there(field, broken) and not _holds(field.get('lockWhen'), broken):
                refused(f"{field['label']}: 맞지 않는 값({wrong_values[field['type']]})은 거절된다", dict(broken, **{field['name']: wrong_values[field['type']]}))
        for where, group in (('', plain), ('줄의 ', [item for item in line_fields if not _computed(item)] if usual else [])):
            for field in group:
                for edge, value, word in (('min', None if field.get('min') is None else field['min'] - 1, '보다 작은'), ('max', None if field.get('max') is None else field['max'] + 1, '보다 큰')):
                    if value is None:
                        continue
                    broken = new_body()
                    if not _there(field, broken['lines'][0] if where else broken, broken if where else None):
                        continue
                    (broken['lines'][0] if where else broken)[field['name']] = value
                    refused(f"{where}{field['label']}: {field[edge]:g} {word} 값({value:g})은 거절된다", broken)
        for where, group in (('', plain), ('줄의 ', [item for item in line_fields if not _computed(item)] if usual else [])):
            for field in [item for item in group if item.get('decimals') is not None]:
                broken, value = new_body(), 10 + 10 ** -(field['decimals'] + 1)
                if not _there(field, broken['lines'][0] if where else broken, broken if where else None):
                    continue
                (broken['lines'][0] if where else broken)[field['name']] = value
                refused(f"{where}{field['label']}: 소수 {field['decimals']}자리를 넘는 값({value:g})은 거절된다", broken)
        for check in definition.get('checks') or []:
            broken = fit(new_body(), definition, framework, made, break_check=check)
            code, answer = post(broken)
            report.add(f"비교 규칙: {check['left']} {check['op']} {check['right']} 을(를) 어기면 거절되고 안내가 나온다 ({check['message']})", code == 400 and (answer or {}).get('detail') == check['message'], f'{code} {answer}')
        for limit in definition.get('limits') or []:
            over = new_body()
            unit = over['lines'][0] if limit.get('lines') else over
            allowed = unit[limit['field']]
            unit[limit['field']] = allowed + 1
            code, answer = post(over)
            report.add(f"한도: {limit['field']} 이(가) {limit['entity']} 의 {limit['entityField']}({allowed:g}) 을(를) 넘으면 거절된다 ({limit['message']})",
                       # (another limit on the same quantity may be the one that speaks: a result held by its instruction and by the order behind it)
                       code == 400 and any(str((answer or {}).get('detail', '')).startswith(same['message']) for same in definition['limits'] if same['field'] == limit['field']), f'{code} {answer}')
            within = new_body()
            code, answer = post(within)
            report.add(f"한도: 꼭 그만큼({(within['lines'][0] if limit.get('lines') else within)[limit['field']]:g})은 저장된다", code == 201, f'{code} {answer}')
        for field in [item for item in plain if item.get('unique')]:
            refused(f"{field['label']}: 이미 있는 값은 거절된다", dict(new_body(), **{field['name']: row[field['name']]}))
        if lines:
            if low > 0:
                refused(f"줄 표: {low}줄보다 적으면 거절된다", new_body(low - 1))
            else:
                code, answer = post(new_body(0))
                report.add('줄 표: 한 줄도 없이 저장할 수 있다', code == 201, f'{code} {answer}')
            if high is not None:
                refused(f"줄 표: {high}줄보다 많으면 거절된다", new_body(high + 1))
        changed = new_body()
        code, updated = framework.call('PUT', f"{api}/{row['id']}", changed)
        same_number = all(updated.get(field['name']) == row.get(field['name']) for field in fields if field.get('type') == 'serial') if code == 200 else False
        kept = [field['label'] for field in plain if field.get('type', 'text') in ('text', 'number', 'date', 'time', 'yesno', 'memo') and code == 200 and updated.get(field['name']) != changed[field['name']]
                and changed[field['name']] is not None and not _holds(field.get('lockWhen'), changed)]
        report.add('수정: 고쳐 저장하면 고친 값이 남는다' + (' (번호는 그대로)' if any(f.get('type') == 'serial' for f in fields) else ''), code == 200 and same_number and not kept, f'{code} {kept or updated}')
        if code == 200:
            log_code, log = framework.call('GET', f"/api/data/{key}/{row['id']}/history")
            whats = [entry.get('what') for entry in log] if log_code == 200 and isinstance(log, list) else []
            report.add('이력: 등록과 수정이 변경 이력에 남는다', whats[-1:] == ['등록'] and '수정' in whats, f'{log_code} {whats}')
            pointing = next((field for field in plain if field.get('type') == 'ref' and isinstance(updated.get(field['name']), int)), None)
            if pointing:        # the way from the record pointed at (as the record stands after the change) back to this screen
                link_code, links = framework.call('GET', f"/api/data/{pointing['ref']['entity']}/{updated[pointing['name']]}/links")
                found = [item for item in (links or {}).get('from', []) if item.get('entity') == key and item.get('field') == pointing['name']] if link_code == 200 else []
                report.add(f"연결: {pointing['label']} 쪽 자료에서 이 화면의 자료로 넘어갈 수 있다", bool(found) and found[0]['count'] >= 1, f'{link_code} {str(links)[:200]}')
        if status:
            names = {value['code']: value['label'] for value in status['values']}
            report.add(f"상태: 새 자료는 {names.get(status['initial'], status['initial'])} 상태로 시작한다", row.get('status') == status['initial'], f"{row.get('status')}")
            for action in status['actions']:
                if status['initial'] not in action['from']:
                    continue                          # reached only through another action; that chain is not walked here
                _, fresh = post(new_body())
                if action.get('separate'):            # kept for a work screen: the entity's own screen must refuse it
                    code, answer = framework.call('POST', f"{api}/{fresh['id']}/actions/{action['name']}")
                    report.add(f"동작 {action['label']}: 등록 화면에서는 거절된다 (업무 화면에서만 한다)", code == 403, f'{code} {answer}')
                    continue
                code, after = framework.call('POST', f"{api}/{fresh['id']}/actions/{action['name']}")
                report.add(f"동작 {action['label']}: {names.get(status['initial'])} 상태에서 되고 {names.get(action['to'], action['to'])} 상태가 된다", code == 200 and after.get('status') == action['to'], f'{code} {after}')
                if action['to'] not in action['from']:
                    code, again = framework.call('POST', f"{api}/{fresh['id']}/actions/{action['name']}")
                    report.add(f"동작 {action['label']}: 이미 {names.get(action['to'], action['to'])} 상태면 거절된다", code == 409, f'{code} {again}')
                if action['to'] in status.get('locked', []):
                    code, answer = framework.call('PUT', f"{api}/{fresh['id']}", new_body())
                    report.add(f"{names.get(action['to'], action['to'])} 상태의 자료는 수정이 거절된다", code == 409, f'{code} {answer}')
        for field in [item for item in plain if item.get('type') == 'ref']:
            code, answer = framework.call('DELETE', f"/api/data/{field['ref']['entity']}/{changed[field['name']]}")
            report.add(f"{field['label']}: 쓰이고 있는 대상 자료는 삭제가 거절된다", code == 409, f'{code} {answer}')
        if not (status and status['initial'] in status.get('locked', [])):
            code, _ = framework.call('DELETE', f"{api}/{row['id']}")
            report.add('삭제: 자료를 지울 수 있다', code == 204, f'{code}')
            gone_code, gone = framework.call('GET', f"{api}/{row['id']}/history")
            report.add('변경 이력: 지운 자료가 언제·누가·지우기 전 내용과 함께 남는다', gone_code == 200 and any(item.get('action') == 'DELETE' and item.get('changes') for item in gone or []), f'{gone_code} {str(gone)[:300]}')
            code, _ = framework.call('PUT', f"{api}/{row['id']}", changed)
            report.add('지운 자료는 더 수정할 수 없다', code == 404, f'{code}')
    finally:
        report.leftover = sweep(framework, made)
    return report


def _summary(part, source, rows):
    """A summary's numbers worked out here, independently of the framework, from the source rows as the data API gives them."""
    line_names = {field['name'] for field in (source.get('lines') or {}).get('fields', [])} if part.get('lines') else set()
    dates = {field['name'] for field in source['fields'] + (source.get('lines') or {}).get('fields', []) if field.get('type') == 'date'}
    groups, everything = {}, [[] for _ in part['values']]
    counts, total_units = {}, 0
    for row in rows:
        for unit in (row.get('lines') or []) if part.get('lines') else [row]:
            keys = []
            for group in part['groupBy']:
                if group['field'] == 'id':
                    keys.append(str(row['id']))
                    continue
                value = row.get('status') if group['field'] == 'status' and group['field'] not in line_names and not any(f['name'] == 'status' for f in source['fields']) \
                    else (unit if group['field'] in line_names else row).get(group['field'])
                text = '' if value is None else str(value)
                if group['field'] in dates and text:
                    text = text[:4] if group.get('by') == 'year' else text[:7] if (group.get('by') or 'month') == 'month' else text
                keys.append(text)
            key = tuple(keys)
            numbers = groups.setdefault(key, [[] for _ in part['values']])
            counts[key] = counts.get(key, 0) + 1
            total_units += 1
            for index, value in enumerate(part['values']):
                if value.get('between'):
                    import datetime
                    start, end = row.get(value['between'][0]), row.get(value['between'][1])
                    number = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days if start and end else None
                    if number is not None:
                        numbers[index].append(number)
                        everything[index].append(number)
                elif value.get('field'):
                    number = (unit if value['field'] in line_names else row).get(value['field'])
                    if isinstance(number, (int, float)):
                        numbers[index].append(number)
                        everything[index].append(number)

    def result(op, numbers, units):
        if op == 'count':
            return units
        if op == 'sum':
            return sum(numbers)          # nothing to add up is 0, not "no value"
        if not numbers:
            return None
        return {'sum': sum(numbers), 'avg': sum(numbers) / len(numbers), 'min': min(numbers), 'max': max(numbers)}[op]
    table = {key: [result(value['op'], numbers[index], counts[key]) for index, value in enumerate(part['values'])] for key, numbers in groups.items()}
    totals = [result(value['op'], everything[index], total_units) for index, value in enumerate(part['values'])]
    return table, totals


def _same(expected, got):
    return (expected is None and got is None) or (expected is not None and got is not None and abs(expected - got) < 0.001)


def summary_checks(key, definition, framework):
    """A summary screen: its groups, computed values, total line and conditions against the same numbers worked out here."""
    report, made, part = Report(), [], definition['summary']
    source = next(item['definition'] for item in framework.definitions() if item['key'] == part['entity'])
    try:
        # Two rows of the source made for the occasion, so there is something to gather even in an empty system.
        for _ in range(2):
            body = {field['name']: sample(field, framework, made) for field in source['fields'] if not _computed(field)}
            if source.get('lines'):
                body['lines'] = [_line(source['lines']['fields'], framework, made, 3), _line(source['lines']['fields'], framework, made, 2)][:source['lines'].get('max') or 2]
            row = framework.ok('POST', f"/api/data/{part['entity']}", fit(body, source, framework, made))
            made.append((part['entity'], row['id']))
        rows = framework.ok('GET', f"/api/data/{part['entity']}")

        plan = (part.get('compare') or {}).get('type') in ('plan', 'minus') and part['compare']
        minus = bool(plan) and plan['type'] == 'minus'
        planned = {}
        if plan:      # one plan row made for the occasion, then every plan row added up by the matching fields
            target = next(item['definition'] for item in framework.definitions() if item['key'] == plan['entity'])
            body = {field['name']: sample(field, framework, made) for field in target['fields'] if not _computed(field)}
            if target.get('lines'):
                body['lines'] = [_line(target['lines']['fields'], framework, made, 2)]
            made.append((plan['entity'], framework.ok('POST', f"/api/data/{plan['entity']}", fit(body, target, framework, made))['id']))
            for item in framework.ok('GET', f"/api/data/{plan['entity']}"):
                for unit in (item.get('lines') or []) if plan.get('lines') else [item]:
                    keys = []
                    for group, mine in zip(part['groupBy'], plan['groupBy']):
                        value = unit.get(mine) if plan.get('lines') and mine in unit else item.get(mine)
                        text = '' if value is None else str(value)
                        keys.append(text[:4] if group.get('by') == 'year' else text[:7] if group.get('by') == 'month' else text)
                    number = unit.get(plan['field']) if plan.get('lines') and plan['field'] in unit else item.get(plan['field'])
                    if isinstance(number, (int, float)):
                        planned[tuple(keys)] = planned.get(tuple(keys), 0) + number

        rows = framework.ok('GET', f"/api/data/{part['entity']}")      # read again: making the other side's sample may have made source rows too

        def earlier(key, by):
            if len(key) == 4:
                return str(int(key) - 1)
            year, month = int(key[:4]), int(key[5:7])
            return f'{year - 1}-{month:02d}' if by == 'year' else (f'{year - 1}-12' if month == 1 else f'{year}-{month - 1:02d}')

        def analysis(answer, table):
            """The comparison, share and ranking columns of the unfiltered answer."""
            mark, labels = part.get('compare'), [value['label'] for value in part['values']]
            of = labels.index(mark['value']) if mark and mark.get('value') in labels else 0
            groups = len(part['groupBy'])
            listed = {tuple(item.get(f'g{index}Key', '') for index in range(groups)): item for item in answer['rows']}
            actual = lambda key: (table[key][of] if key in table else 0) or 0
            if mark:
                wrong = []
                for key, item in listed.items():
                    base = planned.get(key, 0) if minus else planned.get(key) if plan else ((table[(earlier(key[0], mark['by']),) + key[1:]][of]) if (earlier(key[0], mark['by']),) + key[1:] in table else None)
                    rate = (None if actual(key) == 0 else base / actual(key) * 100) if minus and base is not None else None if not base else (actual(key) / base * 100 if plan else (actual(key) - base) / base * 100)
                    expected = (None, None, None) if base is None else (base, actual(key) - base, rate)
                    got = (item.get('c0'), item.get('c1'), item.get('c2'))
                    if not all((e is None and g is None) or (e is not None and g is not None and abs(e - g) < 0.02) for e, g in zip(expected, got)):
                        wrong.append((key, expected, got))
                kind = f"{mark.get('label')}·{mark.get('balance')}·진행률" if minus else '계획·차이·달성률' if plan else f"{mark.get('label') or '이전'}·증감·증감률"
                report.add(f'분석 틀: {kind} 이(가) 줄마다 맞다', not wrong, f'(묶음, 기대, 실제) {wrong[:4]}')
            if part.get('cumulative') and not part.get('top'):
                running, wrong = 0, []
                for item in answer['rows']:
                    running += item.get('v0') or 0
                    if abs((item.get('r0') or 0) - running) > 0.02:
                        wrong.append((item.get('g0'), running, item.get('r0')))
                report.add('분석 틀: 누계가 위에서부터 더한 값과 같다', not wrong, f'{wrong[:4]}')
            if part.get('share'):
                whole = sum(actual(key) for key in set(table) | set(planned))
                wrong = [(key, item.get('s0')) for key, item in listed.items() if whole and abs((item.get('s0') or 0) - actual(key) / whole * 100) > 0.02]
                report.add('분석 틀: 구성비가 줄마다 맞다 (전체 대비 %)', not wrong, f'{wrong[:4]}')
            if part.get('top'):
                order = [item.get('v0') or 0 for item in answer['rows']]
                best = sorted(((table[key][0] or 0) for key in table), reverse=True)[:part['top']]
                report.add(f"분석 틀: 큰 순서로 {part['top']}개까지만 나온다", len(order) <= part['top'] and order == sorted(order, reverse=True) and all(abs(a - b) < 0.001 for a, b in zip(order, best)), f'실제 {order}, 기대 {best}')

        def compare(label, query, chosen):
            code, answer = framework.call('GET', f'/api/summary/{key}' + query)
            if not report.add(f'{label}: 조회된다', code == 200, f'{code} {answer}'):
                return
            table, totals = _summary(part, source, chosen)
            groups = len(part['groupBy'])
            got = {tuple(item.get(f'g{index}Key', '') for index in range(groups)): [item.get(f'v{index}') for index in range(len(part['values']))] for item in answer['rows']}
            if not query:
                analysis(answer, table)
            if part.get('top') or (plan and query):
                # A ranking shows only its largest groups, and a plan under a condition is judged above: here, what is listed must be right.
                report.add(f'{label}: 나온 묶음이 모두 실제 자료에 있다', all(group in table or group in planned for group in got), f'{sorted(set(got) - set(table) - set(planned))}')
            else:
                wanted = set(table) | (set(planned) if plan and not minus else set())
                report.add(f'{label}: 묶음이 같다 ({len(wanted)}개)', set(got) == wanted, f'기대 {sorted(wanted)}, 실제 {sorted(got)}')
            for index, value in enumerate(part['values']):
                wrong = [(group, table[group][index], got[group][index]) for group in table if group in got and not _same(table[group][index], got[group][index])]
                report.add(f"{label}: {value['label']}({value['op']}) 값이 묶음마다 맞다", not wrong, f'(묶음, 기대, 실제) {wrong[:5]}')
                report.add(f"{label}: {value['label']} 의 합계 줄이 맞다", _same(totals[index], answer['totals'].get(f'v{index}')), f"기대 {totals[index]}, 실제 {answer['totals'].get(f'v{index}')}")
            if not query:
                names = [column['label'] for column in answer['columns']]
                wanted = [group['label'] for group in part['groupBy']] + [value['label'] for value in part['values']]
                report.add('열 이름이 정의와 같다', names[:len(wanted)] == wanted, f'{names}')
        compare('전체', '', rows)
        fields = {field['name']: field for field in source['fields']}
        for name in part.get('filters', []):
            if name == 'status':
                code = (source.get('status') or {}).get('initial')
                if code:
                    compare('조회 조건 상태', f'?status={code}', [row for row in rows if row.get('status') == code])
            elif fields.get(name, {}).get('type') == 'date':
                compare(f"조회 조건 {fields[name]['label']} 기간(지난 날짜만)", f'?{name}_to=2000-01-01', [row for row in rows if (row.get(name) or '9') <= '2000-01-01'])
                compare(f"조회 조건 {fields[name]['label']} 기간(전체)", f'?{name}_from=2000-01-01', [row for row in rows if (row.get(name) or '') >= '2000-01-01'])
            elif name in fields and fields[name].get('type') in ('ref', 'code'):
                value = rows[-1].get(name)
                if value is not None:
                    compare(f"조회 조건 {fields[name]['label']}", f'?{name}={value}', [row for row in rows if row.get(name) == value])
    finally:
        report.leftover = sweep(framework, made)
    return report


def take_checks(key, definition, framework):
    """A take-over screen: what an earlier record leaves open is listed, chosen rows become the next-stage record, the open quantity
    goes down by what was taken, and more than is open is refused - tried on an earlier record made for the occasion."""
    report, made, part, api = Report(), [], definition['take'], f'/api/take/{key}'
    earlier = next(item['definition'] for item in framework.definitions() if item['key'] == part['from'])
    target = next(item['definition'] for item in framework.definitions() if item['key'] == part['entity'])
    try:
        code, shape = framework.call('GET', f'{api}/shape')
        if not report.add('화면의 틀을 읽을 수 있다 (만들 자료, 물어볼 항목)', code == 200, f'{code} {shape}'):
            return report
        body = {field['name']: sample(field, framework, made) for field in earlier['fields'] if not _computed(field)}
        if earlier.get('lines'):
            body['lines'] = [_line(earlier['lines']['fields'], framework, made, 6)]
        source = framework.ok('POST', f"/api/data/{part['from']}", fit(body, earlier, framework, made))
        made.append((part['from'], source['id']))
        wanted, status = part.get('statuses') or [], earlier.get('status') or {}
        for _ in range(4):                   # walk the earlier record to a status this screen lists
            if not wanted or source.get('status') in wanted:
                break
            step = next((action for action in status.get('actions', []) if source.get('status') in action['from'] and action['to'] in wanted), None) \
                or next((action for action in status.get('actions', []) if source.get('status') in action['from'] and action['to'] != source.get('status')), None)
            if not step:
                break
            code, after = framework.call('POST', f"/api/data/{part['from']}/{source['id']}/actions/{step['name']}")
            if code != 200:
                break
            source = after
        if wanted and source.get('status') not in wanted:
            report.add(f"앞 단계 자료를 이 화면이 다루는 상태({', '.join(wanted)})로 만들 수 있다", False, f"상태 {source.get('status')} 에서 더 갈 수 없었다")
            return report
        out_stock = target.get('stock') if (target.get('stock') or {}).get('direction') == 'out' else None

        def stocked(payload):
            """When the new entity issues stock, what the chosen rows need is put in first (the check is about taking over, not about stock)."""
            if out_stock:
                limit_ = next(item for item in target.get('limits') or [] if item['entity'] == part['from'])
                theirs = dict(zip(limit_['by'], limit_['entityBy'])).get(out_stock['item'])
                house = (payload.get('values') or {}).get(out_stock['warehouse'])
                listed = {(row['sourceId'], row['line']): row for row in framework.ok('GET', api)}
                for chosen in payload.get('rows') or []:
                    row = listed.get((chosen['sourceId'], chosen['line']))
                    item = ((row.get('unit') or {}).get(theirs) if row else None) or (row['head'].get(theirs) if row else None)
                    if item and house and stock_of(framework, item, house) < chosen['quantity']:
                        framework.ok('POST', '/api/system/stock/adjust', {'itemEntity': out_stock['itemEntity'], 'itemId': item, 'warehouseEntity': out_stock['warehouseEntity'], 'warehouseId': house, 'quantity': chosen['quantity'], 'unitCost': 100})
            return payload
        mine = lambda rows: [row for row in rows if row.get('sourceId') == source['id']]
        code, rows = framework.call('GET', api)
        if not report.add('남은 것 목록이 조회된다', code == 200 and isinstance(rows, list), f'{code} {str(rows)[:200]}'):
            return report
        open_rows = mine(rows)
        report.add('방금 만든 앞 단계 자료가 남은 수량 그대로 목록에 있다', bool(open_rows) and all(row['remaining'] == row['ordered'] and row['done'] == 0 for row in open_rows), f'{open_rows}')
        if not open_rows:
            return report
        values = {field['name']: sample(field, framework, made) for field in target['fields'] if field['name'] in shape.get('ask', []) and not _computed(field)}
        first = open_rows[0]
        part_quantity = max(1, int(first['remaining'] // 2)) if first['remaining'] >= 2 else first['remaining']
        code, answer = framework.call('POST', api, stocked({'values': values, 'rows': [{'sourceId': first['sourceId'], 'line': first['line'], 'quantity': first['remaining'] + 1}]}))
        report.add(f"남은 수량({first['remaining']:g})보다 많이 넘기면 거절된다", code == 400, f'{code} {answer}')
        code, answer = framework.call('POST', api, stocked({'values': values, 'rows': []}))
        report.add('고른 줄이 없으면 거절된다', code == 400, f'{code} {answer}')
        typed = {field['name']: sample(field, framework, made) for field in shape.get('askLines') or [] if field.get('required')}     # what the row asks for and cannot do without
        code, answer = framework.call('POST', api, stocked({'values': values, 'rows': [{'sourceId': first['sourceId'], 'line': first['line'], 'quantity': part_quantity, 'values': typed}]}))
        ok = code in (200, 201) and isinstance(answer, dict) and answer.get('count') == 1
        for item in (answer.get('created') or []) if isinstance(answer, dict) else []:
            made.append((part['entity'], item['id']))
        if not report.add(f"줄을 골라 일부({part_quantity:g})만 넘기면 {target['title']} 자료 한 건이 만들어진다", ok, f'{code} {answer}'):
            return report
        new = framework.ok('GET', f"/api/data/{part['entity']}/{answer['created'][0]['id']}")
        limit = next(item for item in target.get('limits') or [] if item['entity'] == part['from'])
        holder = (new.get('lines') or [{}])[0] if limit.get('lines') else new
        report.add('만들어진 자료에 넘긴 수량이 들어 있다', holder.get(limit['field']) == part_quantity, f"{holder.get(limit['field'])}")
        pointer = next((mine_name for mine_name, theirs in zip(limit['by'], limit['entityBy']) if theirs == 'id'), None)
        if pointer:
            where = holder if pointer in holder else new
            report.add('만들어진 자료가 앞 단계 자료를 가리킨다', where.get(pointer) == source['id'], f'{where.get(pointer)}')
        for into, come in (part.get('set') or {}).items():
            if come not in ('id', 'today'):
                taken_line = (source.get('lines') or [{}])[first['line']] if limit.get('entityLines') and len(source.get('lines') or []) > first['line'] else {}
                expected = taken_line.get(come) if come in taken_line else source.get(come)       # from the earlier line when it is taken line by line
                report.add(f'함께 넘긴 값: {into} 에 앞 단계의 {come} 이(가) 들어 있다', new.get(into) == expected, f'{new.get(into)} / {expected}')
        if shape.get('combinable'):          # two earlier records alike above their lines: one record for both, or one each
            def twin():
                # an earlier record of its own (its lines fitted to whatever stage it hangs on in turn), alike the first above its lines
                again = {field['name']: sample(field, framework, made) for field in earlier['fields'] if not _computed(field)}
                if earlier.get('lines'):
                    again['lines'] = [_line(earlier['lines']['fields'], framework, made, 6)]
                again = fit(again, earlier, framework, made)
                again.update({field['name']: source.get(field['name']) for field in earlier['fields'] if not _computed(field)})
                row = framework.ok('POST', f"/api/data/{part['from']}", again)
                made.append((part['from'], row['id']))
                for _ in range(4):
                    if not wanted or row.get('status') in wanted:
                        break
                    step = next((action for action in status.get('actions', []) if row.get('status') in action['from'] and action['to'] in wanted), None)
                    if not step:
                        break
                    row = framework.ok('POST', f"/api/data/{part['from']}/{row['id']}/actions/{step['name']}")
                return row
            for way, expected, words in (('same', 1, '위쪽 값이 같은 두 건의 줄을 함께 넘기면 한 건으로 묶인다'), ('source', 2, '앞 단계 한 건마다 따로 넘기면 두 건이 만들어진다')):
                pair = [twin(), twin()]
                chosen = [row for row in framework.ok('GET', api) if row.get('sourceId') in (pair[0]['id'], pair[1]['id']) and row['line'] == 0]
                code, both = framework.call('POST', api, stocked({'values': values, 'per': way, 'rows': [{'sourceId': row['sourceId'], 'line': row['line'], 'quantity': 1} for row in chosen]}))
                for item in (both.get('created') or []) if isinstance(both, dict) else []:
                    made.append((part['entity'], item['id']))
                report.add(f'묶는 기준: {words}', code in (200, 201) and len(chosen) == 2 and both.get('count') == expected, f'{code} {both}')
        else:
            code, answer2 = framework.call('POST', api, stocked({'values': values, 'per': 'same', 'rows': [{'sourceId': first['sourceId'], 'line': first['line'], 'quantity': 1}]}))
            report.add('묶는 기준: 앞 단계를 위쪽에서 가리키는 자료는 여러 건을 한 건으로 묶을 수 없다고 거절한다', code == 400, f'{code} {answer2}')
        now = framework.ok('GET', f"/api/data/{part['from']}/{source['id']}")
        if wanted and now.get('status') not in wanted:
            report.add('넘긴 뒤 앞 단계 자료의 상태가 바뀌어 목록에서 빠진다', not mine(framework.ok('GET', api)), '')
            return report
        after = [row for row in mine(framework.ok('GET', api)) if row['line'] == first['line']]
        left = first['remaining'] - part_quantity
        report.add(f'넘긴 만큼 남은 수량이 줄어든다 ({first["remaining"]:g} → {left:g})', (not after and left == 0) or (bool(after) and after[0]['remaining'] == left and after[0]['done'] == part_quantity), f'{after}')
        if left > 0 and after:
            code, answer = framework.call('POST', api, stocked({'values': values, 'rows': [{'sourceId': first['sourceId'], 'line': first['line'], 'quantity': left}]}))
            for item in (answer.get('created') or []) if isinstance(answer, dict) else []:
                made.append((part['entity'], item['id']))
            gone = not [row for row in mine(framework.ok('GET', api)) if row['line'] == first['line']] if code in (200, 201) else False
            report.add('나머지를 모두 넘기면 그 줄은 목록에서 빠진다', gone, f'{code} {answer}')
    finally:
        report.leftover = sweep(framework, made)
    return report


def stock_view_checks(key, definition, framework):
    """A screen that shows the stock: what it reads is there and answers."""
    report = Report()
    show = (definition.get('stockView') or {}).get('show') or 'all'
    for view in (['balance', 'lots', 'moves'] if show == 'all' else [show]):
        code, answer = framework.call('GET', f'/api/stock/{view}')
        report.add(f'재고 보기: {view} 를 읽을 수 있다', code == 200 and isinstance(answer, list), f'{code} {str(answer)[:120]}')
    report.leftover = []
    return report


def stock_view_criteria(definition):
    show = (definition.get('stockView') or {}).get('show') or 'all'
    words = {'balance': '현재고', 'lots': 'LOT', 'moves': '수불 내역'}
    items = [('재고 화면이 있다', {'op': 'visible', 'selector': '[data-ui="stock"]'}), ('목록이 있다', {'op': 'visible', 'selector': '[data-ui="stock"] [data-ui="record-grid"]'})]
    for view in (['balance', 'lots', 'moves'] if show == 'all' else [show]):
        items.append((f'{words[view]} 보기 버튼이 있다', {'op': 'visible', 'selector': f'[data-ui="stock"] >> role=button[name="{words[view]}"]'}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def take_screen_criteria(definition):
    toolbar = '[role="toolbar"][aria-label="업무 버튼"]'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
             ('조회 조건 영역이 있다', {'op': 'visible', 'selector': 'form[data-ui="query-panel"]'}),
             ('남은 것 목록이 있다', {'op': 'visible', 'selector': '[data-ui="take"] [data-ui="record-grid"]'}),
             ('목록에 남은 수량 열이 있다', {'op': 'text', 'selector': '[data-ui="record-grid"]', 'contains': '남은 수량'}),
             ('목록에 이번에 넘길 수량 열이 있다', {'op': 'text', 'selector': '[data-ui="record-grid"]', 'contains': '이번'}),
             ('줄을 고르는 체크 칸이 있다', {'op': 'visible', 'selector': '[data-ui="record-grid"][data-selection="checkbox-multiple"]'})]
    known = {}
    if (definition['take'].get('ask') or (definition['take'].get('lines') or {}).get('ask')):
        import framework as _fw
        target = next((item['definition'] for item in _fw.Framework().definitions() if item['key'] == definition['take']['entity']), None)
        known = {field['name']: field['label'] for field in (((target or {}).get('lines') or {}).get('fields', []) or (target or {}).get('fields', []))}
    for name in definition['take'].get('ask') or (definition['take'].get('lines') or {}).get('ask') or []:
        items.append((f"목록에 줄마다 적는 {known.get(name, name)} 열이 있다", {'op': 'text', 'selector': '[data-ui="record-grid"]', 'contains': known.get(name, name)}))
    for label in ('조회', '저장'):
        items.append((f'공통 버튼 {label} 이(가) 있다', {'op': 'visible', 'selector': f'{toolbar} >> role=button[name="{label}"]'}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def over_checks(key, definition, framework):
    """A work screen: it lists only its statuses, takes only its actions, changes nothing else - tried on records made in the entity it is over."""
    report, made, part = Report(), [], definition['over']
    base = next(item['definition'] for item in framework.definitions() if item['key'] == part['entity'])
    status, api, own = base.get('status') or {}, f'/api/over/{key}', f"/api/data/{part['entity']}"
    names = {value['code']: value['label'] for value in status.get('values', [])}

    def fresh():
        body = {field['name']: sample(field, framework, made) for field in base['fields'] if not _computed(field)}
        if base.get('lines') and base['lines'].get('min', 1) > 0:
            body['lines'] = [_line(base['lines']['fields'], framework, made, 2)]
        body = fit(body, base, framework, made)
        ready_masters(base, body, framework, made)          # registering it may draw on master data (a work order expands its BOM)
        row = framework.ok('POST', own, body)
        made.append((part['entity'], row['id']))
        return row
    try:
        row = fresh()
        code, rows = framework.call('GET', api)
        if not report.add('목록이 조회된다', code == 200, f'{code} {rows}'):
            return report
        if part.get('statuses'):
            shown = ', '.join(names.get(item, item) for item in part['statuses'])
            report.add(f'정한 상태({shown})의 건만 보인다', all(item.get('status') in part['statuses'] for item in rows), f"{sorted({item.get('status') for item in rows})}")
            inside = row.get('status') in part['statuses']
            report.add(f"방금 등록한 건({names.get(row.get('status'), row.get('status'))} 상태)이 목록에 {'있다' if inside else '없다'}", any(item['id'] == row['id'] for item in rows) == inside, '')
        if part.get('create'):
            body = fit({field['name']: sample(field, framework, made) for field in base['fields'] if not _computed(field)}, base, framework, made)
            follows = base.get('follows')
            if follows:                                    # a 기타 screen: it registers without the stage before
                body[follows] = None
            ready_masters(base, body, framework, made)
            code, answer = framework.call('POST', api, body)
            if code in (200, 201):
                made.append((part['entity'], answer['id']))
            report.add('이 화면에서 새로 등록할 수 있다' + (' (앞 단계 없이)' if follows else ''), code in (200, 201), f'{code} {answer}')
            if follows:
                pointed = dict(body, **{follows: sample(next(field for field in base['fields'] if field['name'] == follows), framework, made)})
                code, answer = framework.call('POST', api, pointed)
                if code in (200, 201):
                    made.append((part['entity'], answer['id']))
                report.add('이 화면에서는 앞 단계를 고르면 거절된다', code == 400, f'{code} {answer}')
        else:
            code, answer = framework.call('POST', api, {})
            report.add('이 화면에서는 새로 등록할 수 없다', code in (403, 404, 405), f'{code} {answer}')
        code, answer = framework.call('DELETE', f"{api}/{row['id']}")
        report.add('이 화면에서는 지울 수 없다', code in (403, 404, 405), f'{code} {answer}')
        visible = not part.get('statuses') or row.get('status') in part['statuses']
        if visible:
            again = {name: value for name, value in row.items() if name not in ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt')}
            code, answer = framework.call('PUT', f"{api}/{row['id']}", again)
            report.add('내용을 고칠 수 있다' if part.get('edit') else '내용은 고칠 수 없다', code == (200 if part.get('edit') else 403), f'{code} {answer}')
        for action in status.get('actions', []):
            listed = action['name'] in part.get('actions', [])
            if row.get('status') not in action['from'] or not visible:
                continue
            target = fresh()
            if listed:
                code, after = framework.call('POST', f"{api}/{target['id']}/actions/{action['name']}")
                report.add(f"동작 {action['label']}: 이 화면에서 되고 {names.get(action['to'], action['to'])} 상태가 된다", code == 200 and after.get('status') == action['to'], f'{code} {after}')
                if part.get('statuses') and action['to'] not in part['statuses']:
                    code, _ = framework.call('GET', f"{api}/{target['id']}")
                    report.add(f"동작 {action['label']} 뒤에는 그 건이 이 화면에서 빠진다", code == 404, f'{code}')
            else:
                code, answer = framework.call('POST', f"{api}/{target['id']}/actions/{action['name']}")
                report.add(f"동작 {action['label']}: 이 화면의 동작이 아니라서 거절된다", code == 404, f'{code} {answer}')
            if action.get('separate'):
                other = fresh()
                code, answer = framework.call('POST', f"{own}/{other['id']}/actions/{action['name']}")
                report.add(f"동작 {action['label']}: 등록 화면에서는 거절된다 (이 화면에서만 한다)", code == 403, f'{code} {answer}')
    finally:
        report.leftover = sweep(framework, made)
    return report


def over_screen_criteria(definition):
    toolbar = '[role="toolbar"][aria-label="업무 버튼"]'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
             ('목록이 있다', {'op': 'visible', 'selector': '[data-ui="record-grid"]'}),
             ('내용을 보는 영역이 있다', {'op': 'visible', 'selector': '[data-ui="document-editor"]'}),
             ('공통 버튼 조회 이(가) 있다', {'op': 'visible', 'selector': f'{toolbar} >> role=button[name="조회"]'}),
             ('신규 버튼이 있다' if definition['over'].get('create') else '신규 버튼이 없다', {'op': 'visible' if definition['over'].get('create') else 'absent', 'selector': f'{toolbar} >> role=button[name="신규"]'}),
             ('삭제 버튼이 없다', {'op': 'absent', 'selector': f'{toolbar} >> role=button[name="삭제"]'})]
    saves = definition['over'].get('edit') or definition['over'].get('create')
    items.append(('저장 버튼이 있다' if saves else '저장 버튼이 없다', {'op': 'visible' if saves else 'absent', 'selector': f'{toolbar} >> role=button[name="저장"]'}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def view_checks(key, definition, framework):
    """A calendar or a tree stores nothing: what it shows is tried on records made in the entity it is of."""
    report, made = Report(), []
    part = definition.get('calendar') or definition['tree']
    base = next(item['definition'] for item in framework.definitions() if item['key'] == part['entity'])
    own = f"/api/data/{part['entity']}"

    def fresh(**values):
        body = {field['name']: sample(field, framework, made) for field in base['fields'] if not _computed(field)}
        if base.get('lines') and base['lines'].get('min', 1) > 0:
            body['lines'] = [_line(base['lines']['fields'], framework, made, 1)]
        body = fit(body, base, framework, made)
        body.update(values)
        row = framework.ok('POST', own, body)
        made.append((part['entity'], row['id']))
        return row
    try:
        if definition.get('calendar'):
            values = {part['date']: '2026-03-10'}
            if part.get('end'):
                values[part['end']] = '2026-03-12'
            row = fresh(**values)
            code, answer = framework.call('GET', f'/api/calendar/{key}?month=2026-03')
            found = [item for item in (answer or {}).get('items', []) if item.get('id') == row['id']] if code == 200 else []
            report.add('달력: 그 달의 자료가 날짜와 함께 나온다', bool(found) and found[0].get('date') == '2026-03-10' and bool(found[0].get('label')), f'{code} {str(answer)[:200]}')
            if part.get('end'):
                report.add('달력: 끝 날짜가 함께 나온다 (기간으로 그려진다)', bool(found) and found[0].get('end') == '2026-03-12', f'{found[:1]}')
            code, answer = framework.call('GET', f'/api/calendar/{key}?month=2026-07')
            report.add('달력: 다른 달에는 그 자료가 나오지 않는다', code == 200 and all(item.get('id') != row['id'] for item in answer.get('items', [])), f'{code}')
        elif part.get('child'):
            row = fresh()
            code, answer = framework.call('GET', f'/api/tree/{key}')
            edges = [edge for edge in (answer or {}).get('edges', []) if edge.get('id') == row['id']] if code == 200 else []
            report.add('트리: 상위-하위 한 쌍이 가지로 나온다', bool(edges) and edges[0]['parent'] == row[part['parent']] and edges[0]['child'] == row[part['child']], f'{code} {str(answer)[:200]}')
            report.add('트리: 이어진 자료의 이름이 함께 온다', bool(edges) and all(str(edges[0][side]) in (answer.get('names') or {}) for side in ('parent', 'child')), f"{str((answer or {}).get('names'))[:160]}")
        else:
            top = fresh(**{part['parent']: None})
            below = fresh(**{part['parent']: top['id']})
            code, answer = framework.call('GET', f'/api/tree/{key}')
            nodes = {node['id']: node for node in (answer or {}).get('nodes', [])} if code == 200 else {}
            report.add('트리: 상위가 없는 자료는 맨 위에 온다', top['id'] in nodes and nodes[top['id']].get('parent') is None, f'{code} {str(answer)[:200]}')
            report.add('트리: 하위 자료는 그 상위 아래에 온다', below['id'] in nodes and nodes[below['id']].get('parent') == top['id'] and bool(nodes[below['id']].get('label')), f'{str(nodes.get(below["id"]))[:200]}')
    finally:
        LEFTOVER.extend(sweep(framework, made))
    return report


def view_screen_criteria(definition):
    kind = 'calendar' if definition.get('calendar') else 'tree'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': f'[data-ui="{kind}"]'}), ('화면 이름이 보인다', {'op': 'text', 'selector': f'[data-ui="{kind}"]', 'contains': definition['title']})]
    if kind == 'calendar':
        items += [('월 달력이 그려져 있다', {'op': 'visible', 'selector': '[data-ui="calendar"] [role="grid"]'}), ('다음 달로 넘기는 버튼이 있다', {'op': 'visible', 'selector': '[data-ui="calendar"] >> role=button[name="다음 달"]'})]
    else:
        items += [('트리 표가 있다', {'op': 'visible', 'selector': '[data-ui="tree"] [role="treegrid"]'}), ('모두 접기 버튼이 있다', {'op': 'visible', 'selector': '[data-ui="tree"] >> role=button[name="모두 접기"]'})]
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def dashboard_checks(key, definition, framework):
    """A dashboard stores nothing and computes nothing of its own: every panel must point at a summary that answers."""
    report = Report()
    known = {item['key']: item['definition'] for item in framework.definitions()}
    for panel in definition['dashboard']['panels']:
        code, answer = framework.call('GET', f"/api/summary/{panel['summary']}")
        report.add(f"패널 {panel['title']}: 집계 {panel['summary']} 이(가) 조회된다", code == 200, f'{code} {answer}')
        labels = [value['label'] for value in (known.get(panel['summary'], {}).get('summary') or {}).get('values', [])]
        report.add(f"패널 {panel['title']}: 그릴 값 {panel['value']} 이(가) 그 집계에 있다", panel['value'] in labels, f'{labels}')
    return report


def dashboard_screen_criteria(definition):
    panels = definition['dashboard']['panels']
    items = [('현황판 틀이 있다', {'op': 'visible', 'selector': '[data-ui="dashboard"]'}),
             ('새로 고침 버튼이 있다', {'op': 'visible', 'selector': '[data-ui="dashboard"] >> role=button[name="새로 고침"]'}),
             ('표가 없다 (차트 패널만 있다)', {'op': 'absent', 'selector': '[data-ui="dashboard"] [data-ui="record-grid"]'})]
    for index, panel in enumerate(panels):
        one = f'[data-ui="dashboard-panel"] >> nth={index}'
        items.append((f"패널 {index + 1}: 제목 {panel['title']} 이(가) 보인다", {'op': 'text', 'selector': one, 'contains': panel['title']}))
        inside = '[data-ui="stat-tiles"]' if panel['chart'] == 'figures' else f'[data-ui="chart"][data-kind="{panel["chart"]}"]'
        items.append((f"패널 {index + 1}: {'핵심 숫자' if panel['chart'] == 'figures' else panel['chart'] + ' 차트'}가 그려져 있다", {'op': 'visible', 'selector': f'{one} >> {inside}'}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def summary_screen_criteria(definition):
    part, toolbar, grid = definition['summary'], '[role="toolbar"][aria-label="업무 버튼"]', '[data-ui="record-grid"]'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
             ('집계 표가 있다', {'op': 'visible', 'selector': grid})]
    if part.get('filters'):
        items.append(('조회 조건 영역이 있다', {'op': 'visible', 'selector': 'form[data-ui="query-panel"]'}))
    for label in ('조회', '엑셀', '출력'):
        items.append((f'공통 버튼 {label} 이(가) 있다', {'op': 'visible', 'selector': f'{toolbar} >> role=button[name="{label}"]'}))
    for column in part['groupBy'] + part['values']:
        items.append((f"표에 {column['label']} 열이 있다", {'op': 'text', 'selector': grid, 'contains': column['label']}))
    if part.get('chart'):
        kind = part['chart']['type']
        items.append((f"{part['chart']['value']} 차트({kind})가 있다", {'op': 'visible', 'selector': f'[data-ui="chart"][data-kind="{kind}"]'}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def rule_checks(key, definition, framework):
    """Each blocking rule, on the published entity: blocked while a row points here, allowed once it is gone."""
    report, made, api = Report(), [], f'/api/data/{key}'
    document = bool(definition.get('lines')) and definition['lines'].get('min', 1) > 0
    try:
        for rule in definition.get('rules', []):
            other = next(item['definition'] for item in framework.definitions() if item['key'] == rule['entity'])

            def target():
                if document:
                    body = {field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}
                    body['lines'] = [_line(definition['lines']['fields'], framework, made, 2)]
                else:
                    body = {field['name']: sample(field, framework, made) for field in definition['fields'] if field['required'] and not _computed(field)}
                row = framework.ok('POST', api, fit(body, definition, framework, made))
                made.append((key, row['id']))
                return row

            def attempt(row):
                if rule['action'] == 'delete':
                    return framework.call('DELETE', f"{api}/{row['id']}")
                if rule['action'] == 'update':
                    again = {name: value for name, value in row.items() if name not in ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt')}
                    return framework.call('PUT', f"{api}/{row['id']}", again)
                return framework.call('POST', f"{api}/{row['id']}/actions/{rule['action']}?check=true")   # ask only: the sample row stays deletable
            row = target()
            pointer = {field['name']: (row['id'] if field['name'] == rule['field'] else sample(field, framework, made))
                       for field in other['fields'] if (field['required'] or field['name'] == rule['field']) and not _computed(field)}
            in_lines = any(field['name'] == rule['field'] for field in (other.get('lines') or {}).get('fields', []))
            if other.get('lines') and (other['lines'].get('min', 1) > 0 or in_lines):
                pointer['lines'] = [_line(other['lines']['fields'], framework, made, 1)]
            pointer = fit(pointer, other, framework, made)
            if in_lines:                       # the other entity points here from its lines (after fit: a limit may have pointed the line elsewhere)
                pointer.pop(rule['field'], None)
                pointer['lines'][0][rule['field']] = row['id']
                for limit in other.get('limits') or []:      # the line now points at this record: its quantity must fit what this record allows
                    if limit['entity'] == key and limit.get('lines'):
                        for mine, theirs in zip(limit['by'], limit['entityBy']):
                            if theirs != 'id':
                                pointer['lines'][0][mine] = ((row.get('lines') or [{}])[0] if limit.get('entityLines') else row).get(theirs)
                        pointer['lines'][0][limit['field']] = ((row.get('lines') or [{}])[0] if limit.get('entityLines') else row).get(limit['entityField']) or 1
            for limit in other.get('limits') or []:     # use only part of what this record allows: filling it up may move it on (a fill effect) and lock it
                if limit['entity'] == key and not limit.get('lines') and rule['field'] in limit['by']:
                    whole = row.get(limit['entityField'])
                    if isinstance(whole, (int, float)) and whole >= 2:
                        pointer[limit['field']] = 1
            user = framework.ok('POST', f"/api/data/{rule['entity']}", pointer)
            made.append((rule['entity'], user['id']))
            code, answer = attempt(row)
            report.add(f"규칙: {other['title']} 이(가) 있으면 {rule['action']} 이(가) 거절되고 안내가 나온다 ({rule['message']})",
                       code == 409 and (answer or {}).get('detail') == rule['message'], f'{code} {answer}')
            framework.call('DELETE', f"/api/data/{rule['entity']}/{user['id']}")
            code, answer = attempt(row)
            report.add(f"규칙: {other['title']} 을(를) 지우면 {rule['action']} 이(가) 다시 된다", code in (200, 204), f'{code} {answer}')
    finally:
        report.leftover = sweep(framework, made)
    return report


def effect_checks(key, definition, framework):
    """What follows by itself, on the published entity: the record that should appear does, with the values carried over;
    the record pointed at changes status. Everything made here is removed again (by force where a status locks it)."""
    report, made, api = Report(), [], f'/api/data/{key}'
    known = {item['key']: item['definition'] for item in framework.definitions()}
    status = definition.get('status') or {}
    line_names = [field['name'] for field in (definition.get('lines') or {}).get('fields', [])]

    def source(extra=None):
        body = {field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}
        if definition.get('lines'):
            body['lines'] = [_line(definition['lines']['fields'], framework, made, 2)]
        body = fit(dict(body, **(extra or {})), definition, framework, made)
        ready_masters(definition, body, framework, made)        # registering it may draw on master data (a work order expands its BOM)
        row = framework.ok('POST', api, body)
        made.append((key, row['id']))
        return row

    def trigger(row, on):
        if on == 'create':
            return 201, row
        action = next(item for item in status['actions'] if item['name'] == on)
        if row.get('status') not in action['from']:        # one step first, when the action does not start from the first status
            step = next((item for item in status['actions'] if row.get('status') in item['from'] and item['to'] in action['from']), None)
            if step:
                framework.call('POST', f"{api}/{row['id']}/actions/{step['name']}")
        return framework.call('POST', f"{api}/{row['id']}/actions/{on}")
    try:
        for effect in definition.get('effects') or []:
            when = '등록하면' if effect['on'] == 'create' else next((item['label'] for item in status.get('actions', []) if item['name'] == effect['on']), effect['on']) + ' 하면'
            if effect.get('create'):
                make, other = effect['create'], known[effect['create']['entity']]
                before = {item['id'] for item in framework.ok('GET', f"/api/data/{make['entity']}")}
                row = source()
                code, answer = trigger(row, effect['on'])
                new = [item for item in framework.ok('GET', f"/api/data/{make['entity']}") if item['id'] not in before]
                for item in new:
                    made.append((make['entity'], item['id']))
                if not report.add(f"자동 처리: {when} {other['title']} 이(가) 한 건 만들어진다", code in (200, 201) and len(new) == 1, f'{code} {answer} / 새로 생긴 {len(new)}건'):
                    continue
                today = __import__('datetime').date.today().isoformat()
                wrong = [(into, new[0].get(into)) for into, come in make['set'].items()
                         if new[0].get(into) != (row['id'] if come == 'id' else today if come == 'today' else row.get(come))]
                report.add(f"자동 처리: 만들어진 {other['title']} 에 값이 그대로 옮겨진다 ({', '.join(make['set'])})", not wrong, f'다른 값 {wrong}')
                if make.get('lines'):
                    got = [[line.get(into) for into in make['lines']['set']] for line in new[0].get('lines', [])]
                    want = [[line.get(come) for come in make['lines']['set'].values()] for line in row.get('lines', [])]
                    report.add('자동 처리: 줄 표도 줄마다 옮겨진다', got == want, f'기대 {want}, 실제 {got}')
            elif effect.get('expand'):
                part = dict(effect['expand'])
                if isinstance(part.get('quantity'), dict):          # as written: {"into", "line", "times"}
                    part.update(quantityInto=part['quantity'].get('into'), quantityLine=part['quantity'].get('line'), quantityTimes=part['quantity'].get('times'))
                master, target = known[part['from']], known[part['into']]
                newest = lambda key: max([row['id'] for row in framework.ok('GET', f'/api/data/{key}?_sort=id&_desc=true&_limit=1')] or [0])
                body = {field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}
                body = fit(body, definition, framework, made)
                if part.get('quantityTimes'):
                    body[part['quantityTimes']] = 3
                given = {field['name']: sample(field, framework, made) for field in master['fields'] if not _computed(field)}
                if master.get('lines'):
                    given['lines'] = [_line(master['lines']['fields'], framework, made, 2 + index) for index in range(2)]
                for theirs, mine in part['match'].items():
                    given[theirs] = body.get(mine)
                given = fit(given, master, framework, made)
                for theirs, mine in part['match'].items():
                    given[theirs] = body.get(mine)
                if master.get('effective'):          # valid on the day this record is for
                    given[master['effective']['from']] = '2000-01-01'
                    if master['effective'].get('to'):
                        given[master['effective']['to']] = None
                code, kept = framework.call('POST', f"/api/data/{part['from']}", given)
                if not report.add(f"펼치기: 맞는 {master['title']} 을(를) 준비한다", code == 201, f'{code} {kept}'):
                    continue
                made.append((part['from'], kept['id']))
                mark = newest(part['into'])
                code, row = framework.call('POST', api, body)
                if code == 201:
                    made.append((key, row['id']))
                    if effect['on'] != 'create':
                        code, row = trigger(row, effect['on'])
                new = [item for item in framework.ok('GET', f"/api/data/{part['into']}?_sort=id&_desc=true&_limit=200") if item['id'] > mark]
                for item in new:
                    made.append((part['into'], item['id']))
                times = float(body.get(part['quantityTimes']) or 0) if part.get('quantityTimes') else 1
                wanted = sorted(float(line.get(part['quantityLine']) or 0) * times for line in (kept.get('lines') if master.get('lines') else [kept]))
                got = sorted(float(item.get(part['quantityInto']) or 0) for item in new)
                report.add(f"펼치기: {when} {master['title']} 의 줄마다 {target['title']} 이(가) 한 건씩 생기고 수량은 줄 수량 × 이 자료 수량이다", code in (200, 201) and got == wanted, f'{code} 기대 {wanted}, 생긴 것 {got}')
                for into, come in (part.get('set') or {}).items():
                    if come == 'id':
                        report.add(f"펼치기: 생긴 {target['title']} 의 {into} 이(가) 이 자료를 가리킨다", bool(new) and all(item.get(into) == (row or {}).get('id') for item in new), f"{[item.get(into) for item in new]}")
                if new and part.get('quantityLine'):
                    # what was drawn is kept as it was at that moment: changing the master afterwards changes nothing already made
                    meta = ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt', '_names', '_files', '_stock')
                    record = framework.ok('GET', f"/api/data/{part['from']}/{kept['id']}")
                    changed = {name: value for name, value in record.items() if name not in meta}
                    holder = changed['lines'][0] if master.get('lines') and changed.get('lines') else changed
                    holder[part['quantityLine']] = float(holder.get(part['quantityLine']) or 0) + 5
                    code, answer = framework.call('PUT', f"/api/data/{part['from']}/{kept['id']}", changed)
                    after = sorted(float(framework.ok('GET', f"/api/data/{part['into']}/{item['id']}").get(part['quantityInto']) or 0) for item in new)
                    report.add(f"펼치기: 나중에 {master['title']} 을(를) 바꿔도 이미 생긴 {target['title']} 은(는) 그대로다", code == 200 and after == got,
                               f'{code} {answer if code != 200 else ""} 바꾸기 전 {got}, 바꾼 뒤 {after}')
                lone = {field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}
                lone = fit(lone, definition, framework, made)
                if effect['on'] == 'create' and any(lone.get(mine) != body.get(mine) for mine in part['match'].values()):
                    code, answer = framework.call('POST', api, lone)
                    if code == 201:
                        made.append((key, answer['id']))
                    report.add(f"펼치기: 맞는 {master['title']} 이(가) 없으면 등록이 거절되고 이유가 나온다", code in (400, 409) and '기준 정보' in str((answer or {}).get('detail')), f'{code} {answer}')
                if effect['on'] == 'create' and master.get('effective'):
                    # which day the master must be valid on: the record's own date (at) or the day it is registered - a master valid only
                    # from tomorrow, and a record dated after that
                    import datetime
                    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
                    later_day = (datetime.date.today() + datetime.timedelta(days=11)).isoformat()
                    dated = fit({field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}, definition, framework, made)
                    if any(dated.get(mine) != body.get(mine) for mine in part['match'].values()):
                        given = {field['name']: sample(field, framework, made) for field in master['fields'] if not _computed(field)}
                        if master.get('lines'):
                            given['lines'] = [_line(master['lines']['fields'], framework, made, 2 + index) for index in range(2)]
                        for theirs, mine in part['match'].items():
                            given[theirs] = dated.get(mine)
                        given = fit(given, master, framework, made)
                        for theirs, mine in part['match'].items():
                            given[theirs] = dated.get(mine)
                        given[master['effective']['from']] = tomorrow
                        if master['effective'].get('to'):
                            given[master['effective']['to']] = None
                        code, future = framework.call('POST', f"/api/data/{part['from']}", given)
                        if code == 201:
                            made.append((part['from'], future['id']))
                            for field in definition['fields']:
                                if field.get('type') == 'date':
                                    dated[field['name']] = later_day
                            if part.get('quantityTimes'):
                                dated[part['quantityTimes']] = 3
                            code, answer = framework.call('POST', api, dated)
                            if code == 201:
                                made.append((key, answer['id']))
                            if part.get('at'):
                                label = next((field['label'] for field in definition['fields'] if field['name'] == part['at']), part['at'])
                                report.add(f"펼치기: {label} 에 유효한 {master['title']} 을(를) 쓴다 (내일부터 유효한 것도 {label} 이(가) 그 뒤면 쓰인다)", code == 201, f'{code} {answer}')
                            else:
                                report.add(f"펼치기: 등록하는 날(오늘) 유효한 {master['title']} 만 쓴다 (내일부터 유효한 것은 날짜 항목이 그 뒤여도 쓰이지 않는다)",
                                           code in (400, 409) and '기준 정보' in str((answer or {}).get('detail')), f'{code} {answer}')
            elif effect.get('fill'):
                fill, other = effect['fill'], known[effect['fill']['entity']]
                wanted = next(item for item in other['status']['actions'] if item['name'] == fill['action'])
                names = {value['code']: value['label'] for value in other['status']['values']}
                limit = next(item for item in definition['limits'] if item['entity'] == fill['entity'] and 'id' in item['entityBy'])
                pointer = limit['by'][limit['entityBy'].index('id')]

                def fresh(entity, about, point=None):
                    """A record of another stage, made whole; point: (field, id) it must point at (so its quantities are that record's)."""
                    body = {field['name']: sample(field, framework, made) for field in about['fields'] if not _computed(field)}
                    if about.get('lines'):
                        body['lines'] = [_line(about['lines']['fields'], framework, made, 4)]
                    if point:
                        in_line = any(field['name'] == point[0] for field in (about.get('lines') or {}).get('fields', []))
                        (body['lines'][0] if in_line else body)[point[0]] = point[1]
                    made_row = framework.ok('POST', f'/api/data/{entity}', fit(body, about, framework, made))
                    made.append((entity, made_row['id']))
                    return made_row
                first = fresh(fill['entity'], other)             # the earlier record, brought to where the action starts
                for _ in range(4):
                    if first.get('status') in wanted['from']:
                        break
                    step = next((item for item in other['status']['actions'] if first.get('status') in item['from'] and item['to'] in wanted['from']), None) \
                        or next((item for item in other['status']['actions'] if first.get('status') in item['from'] and item['name'] != wanted['name']), None)
                    if not step:
                        break
                    first = framework.ok('POST', f"/api/data/{fill['entity']}/{first['id']}/actions/{step['name']}")
                body = {field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}
                if definition.get('lines'):
                    body['lines'] = [_line(definition['lines']['fields'], framework, made, 4)]
                place = lambda name: body['lines'][0] if name in line_names else body
                for between in definition['limits']:            # a stage in between (an instruction between the order and this result) is made from the same earlier record
                    middle = known.get(between['entity'])
                    via = next((item for item in (middle or {}).get('limits') or [] if item['entity'] == fill['entity'] and 'id' in item['entityBy']), None)
                    if between is limit or not via or 'id' not in between['entityBy']:
                        continue
                    stage = fresh(between['entity'], middle, (via['by'][via['entityBy'].index('id')], first['id']))
                    place(between['by'][between['entityBy'].index('id')])[between['by'][between['entityBy'].index('id')]] = stage['id']
                place(pointer)[pointer] = first['id']
                whole = first.get(limit['entityField'])
                if not limit.get('lines') and not limit.get('entityLines') and isinstance(whole, (int, float)) and whole >= 2 and first.get('status') in wanted['from']:
                    # part of it first: the earlier record stays where it is; the rest then fills it
                    part = fit(dict(body), definition, framework, made)          # (the sample is readied first: it would fill the quantity up to the limit)
                    part[limit['field']] = whole // 2
                    code, half = framework.call('POST', api, part)
                    if code == 201:
                        made.append((key, half['id']))
                    between_status = framework.ok('GET', f"/api/data/{fill['entity']}/{first['id']}").get('status')
                    report.add(f"자동 처리: 일부만({whole // 2:g}/{whole:g}) 채우면 {other['title']} 은(는) 아직 {names.get(between_status, between_status)} 그대로다",
                               code == 201 and between_status in wanted['from'], f"{code} {half if code != 201 else ''} / 상태 {between_status}")
                    body = fit(body, definition, framework, made)
                    body[limit['field']] = whole - whole // 2
                else:
                    body = fit(body, definition, framework, made)
                code, row = framework.call('POST', api, body)
                if code == 201:
                    made.append((key, row['id']))
                after = framework.ok('GET', f"/api/data/{fill['entity']}/{first['id']}")
                report.add(f"자동 처리: 등록해서 {other['title']} 의 수량이 다 차면 그 자료가 {names.get(wanted['to'], wanted['to'])} 상태가 된다",
                           code == 201 and first.get('status') in wanted['from'] and after.get('status') == wanted['to'], f"{code} {row if code != 201 else ''} / 앞 단계 상태 {first.get('status')} → {after.get('status')}")
            elif effect.get('cascade'):
                part, other = effect['cascade'], known[effect['cascade']['entity']]
                wanted = next(item for item in other['status']['actions'] if item['name'] == part['action'])
                names = {value['code']: value['label'] for value in other['status']['values']}
                row = source()
                # the records that point at it: made by it already (planned issues from a work order), or one made here
                children = [item for item in framework.ok('GET', f"/api/data/{part['entity']}?{part['via']}={row['id']}&_limit=100") if item.get(part['via']) == row['id']]
                if not children:
                    body = fit({field['name']: sample(field, framework, made) for field in other['fields'] if not _computed(field)}, other, framework, made)
                    body[part['via']] = row['id']
                    for limit in other.get('limits') or []:
                        if limit['entity'] == key and not limit.get('lines'):
                            body[limit['field']] = 1
                    code, child = framework.call('POST', f"/api/data/{part['entity']}", body)
                    if code == 201:
                        children = [child]
                for child in children:
                    made.append((part['entity'], child['id']))
                ready = [child for child in children if child.get('status') in wanted['from']]
                if not ready:
                    continue                  # nothing that points at it could be made here (only through its own flow): left to the flows
                code, answer = trigger(row, effect['on'])
                after = [framework.ok('GET', f"/api/data/{part['entity']}/{child['id']}").get('status') for child in ready]
                report.add(f"자동 처리: {when} 이 자료를 가리키는 {other['title']} 도 {names.get(wanted['to'], wanted['to'])} 상태가 된다 (아래로 전파)",
                           code == 200 and all(state == wanted['to'] for state in after), f"{code} {answer if code != 200 else ''} / {len(ready)}건, 지금 상태 {after}")
            else:
                act = effect['act']
                pointer = next(field for field in definition['fields'] if field['name'] == act['via'])
                other = known[pointer['ref']['entity']]
                wanted = next(item for item in other['status']['actions'] if item['name'] == act['action'])
                if effect['on'] == 'create':
                    # The record pointed at must already stand where the action starts, so it is made and brought there first.
                    pointed = sample(pointer, framework, made)
                    target = f"/api/data/{pointer['ref']['entity']}/{pointed}"
                    fresh = framework.ok('GET', target)
                    if fresh.get('status') not in wanted['from']:
                        step = next((item for item in other['status']['actions'] if fresh.get('status') in item['from'] and item['to'] in wanted['from']), None)
                        if step:
                            framework.call('POST', f"{target}/actions/{step['name']}")
                    row = source({act['via']: pointed})
                    code, answer = 201, row
                else:
                    row = source()
                    target = f"/api/data/{pointer['ref']['entity']}/{row[act['via']]}"
                    code, answer = trigger(row, effect['on'])
                after = framework.ok('GET', target)
                names = {value['code']: value['label'] for value in other['status']['values']}
                report.add(f"자동 처리: {when} 가리키는 {other['title']} 이(가) {names.get(wanted['to'], wanted['to'])} 상태가 된다 (그 동작을 할 수 있는 상태일 때)",
                           code in (200, 201) and (after.get('status') == wanted['to'] or after.get('status') not in wanted['from']), f"{code} / 지금 상태 {after.get('status')}")
    finally:
        report.leftover = sweep(framework, made)
    return report


def closed_checks(key, definition, framework):
    """A finished record (status.closed: closed early, cancelled, done) takes nothing more: it leaves the take-over lists of the next stage,
    a record of the next stage newly pointing at it is refused, and an action that takes it back out of the finished state lets it go on."""
    report, made, api = Report(), [], f'/api/data/{key}'
    status = definition.get('status') or {}
    closed = status.get('closed') or []
    if not closed:
        return report
    known = {item['key']: item['definition'] for item in framework.definitions()}
    names = {value['code']: value['label'] for value in status['values']}
    ending = next((item for item in status['actions'] if item['to'] in closed and status['initial'] in item['from']), None)
    if not ending:
        return report
    takes = [(other, one['take']) for other, one in known.items() if one.get('take') and one['take'].get('from') == key]
    followers = [(other, one, limit) for other, one in known.items() for limit in one.get('limits') or [] if limit['entity'] == key and 'id' in limit['entityBy']]
    try:
        body = {field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}
        if definition.get('lines'):
            body['lines'] = [_line(definition['lines']['fields'], framework, made, 2)]
        body = fit(body, definition, framework, made)
        ready_masters(definition, body, framework, made)
        row = framework.ok('POST', api, body)
        made.append((key, row['id']))
        code, answer = framework.call('POST', f"{api}/{row['id']}/actions/{ending['name']}")
        if not report.add(f"끝난 상태: {ending['label']} 하면 {names.get(ending['to'])} 상태가 된다", code == 200, f'{code} {answer}'):
            return report
        for take_key, take in takes:
            listed = [item for item in framework.ok('GET', f'/api/take/{take_key}') if item.get('sourceId') == row['id']]
            report.add(f"끝난 상태: {names.get(ending['to'])} 인 자료는 이어받기 화면({known[take_key]['title']}) 목록에 나오지 않는다", not listed, f'{len(listed)}줄이 남아 있음')
        for other, one, limit in followers[:2]:
            pointer = limit['by'][limit['entityBy'].index('id')]
            follow = fit({field['name']: sample(field, framework, made) for field in one['fields'] if not _computed(field)}, one, framework, made)
            follow[pointer] = row['id']
            if not limit.get('lines'):
                follow[limit['field']] = 1
            code, answer = framework.call('POST', f'/api/data/{other}', follow)
            if code == 201:
                made.append((other, answer['id']))
            said = str((answer or {}).get('detail'))
            if code != 201 and '이어서 등록할 수 없' not in said and '마감' not in said and '이어받기' in said:
                continue             # the next stage is registered only through its take-over screen: that list was checked above
            report.add(f"끝난 상태: {names.get(ending['to'])} 인 자료를 가리키는 {one['title']} 은(는) 새로 등록할 수 없다", code in (400, 409) and '이어서 등록할 수 없' in said, f'{code} {answer}')
        back = next((item for item in status['actions'] if ending['to'] in item['from'] and item['to'] not in closed), None)
        if back and takes:
            code, answer = framework.call('POST', f"{api}/{row['id']}/actions/{back['name']}")
            listed = [item for item in framework.ok('GET', f'/api/take/{takes[0][0]}') if item.get('sourceId') == row['id']]
            report.add(f"끝난 상태: {back['label']} 하면 다시 이어받기 목록에 나온다", code == 200 and bool(listed), f'{code} {answer if code != 200 else ""} / {len(listed)}줄')
    finally:
        report.leftover = sweep(framework, made)
    return report


def rich(definition):
    """The framework draws these with the screen that has a number line, status buttons and a lines table."""
    return bool(definition.get('lines') or definition.get('status') or any(field.get('type') == 'serial' for field in definition['fields']))


def document_screen_criteria(definition):
    import standard_contract
    editor, table, toolbar = '[data-ui="document-editor"]', '[data-ui="document-lines"]', '[role="toolbar"][aria-label="업무 버튼"]'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
             ('조회 조건 영역이 있다', {'op': 'visible', 'selector': 'form[data-ui="query-panel"]'}),
             ('목록이 있다', {'op': 'visible', 'selector': '[data-ui="record-grid"]'}),
             ('입력 영역이 있다', {'op': 'visible', 'selector': editor})]
    if definition.get('lines'):
        items.append(('줄 표가 있다', {'op': 'visible', 'selector': table}))
    if definition.get('status'):
        items.append(('목록에 상태 열이 있다', {'op': 'text', 'selector': '[data-ui="record-grid"]', 'contains': '상태'}))
    for label in ('조회', '신규', '저장', '삭제'):
        items.append((f'공통 버튼 {label} 이(가) 있다', {'op': 'visible', 'selector': f'{toolbar} >> role=button[name="{label}"]'}))
    for field in definition['fields']:
        if field.get('formula') or field.get('sum') or field['type'] == 'serial':
            items.append((f"입력 영역에 {field['label']} 이(가) 보인다", {'op': 'text', 'selector': editor, 'contains': field['label']}))
        elif field.get('showWhen') and not _holds(field['showWhen'], {}):
            pass                                  # there only under another field's value: an empty form does not show it
        else:
            items.append((f"입력 영역에 {field['label']} 입력칸이 있다", {'op': 'visible', 'selector': f'{editor} >> {standard_contract.by_label(field["label"])}'}))
        items.append((f"목록에 {field['label']} 열이 있다", {'op': 'text', 'selector': '[data-ui="record-grid"]', 'contains': field['label']}))
    for field in (definition.get('lines') or {}).get('fields', []):
        items.append((f"줄 표에 {field['label']} 열이 있다", {'op': 'text', 'selector': table, 'contains': field['label']}))
    for more in definition.get('moreLines') or []:
        other = f'[data-ui="document-lines-{more["name"]}"]'
        items.append((f"줄 표 {more['label']} 이(가) 있다", {'op': 'visible', 'selector': other}))
        for field in more['fields']:
            items.append((f"줄 표 {more['label']} 에 {field['label']} 열이 있다", {'op': 'text', 'selector': other, 'contains': field['label']}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def screen_checks(title, definition, record_to, app):
    """Open the screen in a real browser (read-only) and look for what the definition promises."""
    sys.path.insert(0, str(HARNESS))
    import standard_contract
    if definition.get('stockView'):
        criteria = stock_view_criteria(definition)
    elif definition.get('take'):
        criteria = take_screen_criteria(definition)
    elif definition.get('calendar') or definition.get('tree'):
        criteria = view_screen_criteria(definition)
    elif definition.get('over'):
        criteria = over_screen_criteria(definition)
    elif definition.get('dashboard'):
        criteria = dashboard_screen_criteria(definition)
    elif definition.get('summary'):
        criteria = summary_screen_criteria(definition)
    elif rich(definition):
        criteria = document_screen_criteria(definition)
    else:
        sheet = {'path': '/api/x', 'fields': [{'name': field['name'], 'label': field['label'], 'required': field['required'], 'sample': 'x'} for field in definition['fields']
                                              if not field.get('showWhen') or _holds(field['showWhen'], {})]}
        criteria = standard_contract.screen_criteria(sheet)
    if not any(definition.get(part) for part in ('summary', 'dashboard', 'over', 'calendar', 'tree', 'take', 'stockView')):
        criteria.append({'id': f'C{len(criteria) + 1}', 'requirement_id': 'R1', 'description': '한 건을 양식으로 뽑는 출력 버튼이 있다',
                         'check': {'op': 'visible', 'selector': '[role="toolbar"][aria-label="업무 버튼"] >> role=button[name="출력"]'}})
    out = Path(record_to) / 'browser'
    data = {'open_screen': title, 'contract': {'criteria': criteria, 'requirements': []}, 'preview_url': app + '/?drafts=1', 'api_url': '',
            'output_dir': str(out / uuid.uuid4().hex), 'allow_browser_writes': False, 'allow_api_writes': False}
    # The browser signs in to the project in hand: its addresses and its own checking account.
    from framework import site
    env = dict(os.environ, HARNESS_AUTH_ORIGINS=f'{app},{site().api_url}', HARNESS_LOGIN_CREDENTIALS=str(site().credentials))
    done = subprocess.run(['node', str(HARNESS / 'react_layout_inspector.cjs')], input=json.dumps(data), text=True, capture_output=True, timeout=240, env=env)
    report = Report()
    try:
        results = {result['id']: result for result in json.loads(done.stdout).get('results', [])}
    except ValueError:
        report.add('화면 확인을 실행한다', False, (done.stderr or done.stdout)[-300:])
        return report
    for criterion in criteria:
        result = results.get(criterion['id'], {})
        report.add('화면: ' + criterion['description'], result.get('status') == 'passed', result.get('reason', '결과 없음'))
    return report

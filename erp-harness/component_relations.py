"""Use declared layout and slot relations after semantic candidate retrieval."""
import re


def requested_layout(query):
    editor = r'(?:편집(?:\s*패널|\s*영역|\s*탭)?|\beditor(?:\s*panel)?\b)'
    directions = {
        'bottom': r'(?:하단|아래(?:쪽)?|\bbottom\b)',
        'top': r'(?:상단|위쪽|\btop\b)',
        'left': r'(?:좌측|왼쪽|\bleft\b)',
        'right': r'(?:우측|오른쪽|\bright\b)',
    }
    placements = set()
    for placement, direction in directions.items():
        before = direction + r'[^.!?\n,]{0,36}' + editor
        after = editor + r'[^.!?\n,]{0,18}(?:at|on|to|을|는|은|를)[^.!?\n,]{0,8}' + direction
        if re.search(before, query, re.I) or re.search(after, query, re.I):
            placements.add(placement)
    return {'editor': placements.pop()} if len(placements) == 1 else {}


def slot_contracts(component):
    return list(dict.fromkeys(cid for ids in component.get('slots', {}).values() for cid in ids))


def compatible(component, constraints):
    layout = component.get('layout', {})
    return all(role not in layout or layout[role] == value for role, value in constraints.items())


def order_hits(catalog, hits, query):
    constraints = requested_layout(query)
    if not constraints:
        return hits, constraints
    matches = [cid for cid, entry in catalog.items() if entry['kind'] == 'pattern'
               and all(entry.get('layout', {}).get(role) == value for role, value in constraints.items())]
    # Explicit capabilities can recover a suitable pattern outside vector top-k.
    # This traverses the already loaded bounded catalog, without another search.
    matches.sort(key=lambda cid: (hits.index(cid) if cid in hits else len(hits), cid))
    remaining = [cid for cid in hits if cid not in matches and compatible(catalog[cid], constraints)]
    return matches + remaining, constraints

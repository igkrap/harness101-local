import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from candidate_effective_catalog import effective_catalog


def node(name, source='original'):
    return dict(id=name, kind='JsxElement', label=name, source=source)


class EffectiveCatalogTests(unittest.TestCase):
    def test_retained_active_source_replaces_old_source_and_hides_overlaps(self):
        catalog = [node(n) for n in ['parent', 'retained', 'child', 'query', 'insideSlot', 'boundarySlot', 'outsideSlot']]
        ranges = dict(parent=(0, 100), retained=(10, 40), child=(20, 30), query=(60, 80), insideSlot=(20, 20), boundarySlot=(40, 40), outsideSlot=(101, 101))
        proposal = dict(edits=[dict(node_id='retained', code='active corrected form')])
        original = copy.deepcopy(catalog)
        result = effective_catalog(catalog, proposal, ranges)
        self.assertEqual([n['id'] for n in result], ['retained', 'query', 'outsideSlot'])
        self.assertEqual(result[0]['source'], 'active corrected form')
        self.assertEqual(catalog, original)

    def test_retained_insertion_keeps_new_code_and_hides_conflicting_targets(self):
        catalog = [node(n) for n in ['before', 'slot', 'sameStart', 'parent', 'after']]
        ranges = dict(before=(0, 9), slot=(10, 10), sameStart=(10, 11), parent=(0, 30), after=(11, 20))
        result = effective_catalog(catalog, dict(edits=[dict(node_id='slot', code='const query="";')]), ranges)
        self.assertEqual([n['id'] for n in result], ['before', 'slot', 'after'])
        self.assertEqual(result[1]['source'], 'const query="";')

    def test_missing_ranges_do_not_manufacture_unknown_edit_ids(self):
        result = effective_catalog([node('real')], dict(edits=[dict(node_id='invented', code='wrong')]), {})
        self.assertEqual([n['id'] for n in result], ['real'])

    def test_multiple_disjoint_retained_nodes_keep_order_and_metadata(self):
        catalog = [node('a'), node('between'), node('b')]
        result = effective_catalog(catalog, dict(edits=[dict(node_id='a', code='new a'), dict(node_id='b', code='new b')]), dict(a=(0, 10), between=(11, 20), b=(21, 30)))
        self.assertEqual([n['source'] for n in result], ['new a', 'original', 'new b'])
        self.assertEqual(result[2]['label'], 'b')

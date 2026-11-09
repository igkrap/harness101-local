import copy
import unittest
from types import SimpleNamespace

import test_candidate_targets as target_tests
from candidate_leaf_scope import leaf_scope


class CandidateLeafScopeTests(unittest.TestCase):
    setUp = target_tests.CandidateTargetTests.setUp
    tearDown = target_tests.CandidateTargetTests.tearDown

    def test_named_panels_remain_and_their_large_ancestor_is_hidden(self):
        before = copy.deepcopy(self.catalog)
        result = leaf_scope(self.catalog, self.ed._snapshots[self.snap['snapshot_id']], [self.aside['id']])
        ids = {n['id'] for n in result}
        self.assertIn(self.aside['id'], ids)
        self.assertNotIn(self.main['id'], ids)
        self.assertIn(self.slot['id'], ids)
        self.assertEqual(self.catalog, before)
        self.assertEqual(self.file.read_text(), self.source)

    def test_explicit_target_or_retained_ancestor_is_never_hidden(self):
        result = leaf_scope(self.catalog, self.ed._snapshots[self.snap['snapshot_id']], [self.main['id']])
        self.assertIn(self.main['id'], {n['id'] for n in result})

    def test_missing_snapshot_ranges_does_not_guess(self):
        for snapshot in [None, SimpleNamespace(nodes={}, ranges={})]:
            self.assertEqual(leaf_scope(self.catalog, snapshot), self.catalog)

    def test_unknown_ranges_and_non_jsx_nodes_are_preserved(self):
        extra = {'id': 'unknown', 'kind': 'JsxElement', 'source': '<section/>', 'label': 'unknown'}
        catalog = self.catalog + [extra]
        result = leaf_scope(catalog, self.ed._snapshots[self.snap['snapshot_id']])
        self.assertIn(extra, result)
        self.assertEqual([n for n in result if n['kind'] != 'JsxElement'], [n for n in catalog if n['kind'] != 'JsxElement'])

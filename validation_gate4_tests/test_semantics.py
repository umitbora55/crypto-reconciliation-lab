"""Adversarial controls for the Gate4 semantic evidence checker, not old tests."""
import copy
import unittest
from validation_lab.gate4_semantics import compare_pair, quantities


class Gate4SemanticEvidenceTests(unittest.TestCase):
    def test_same_count_substituted_receipt_does_not_pass_pair(self):
        good={'observations':{'receipt_hashes':['a','b']},'logical_before_reopen':{},'logical_after_reopen':{},'canonical_files':{}}
        bad=copy.deepcopy(good);bad['observations']['receipt_hashes'][1]='substitution'
        with self.assertRaisesRegex(AssertionError,'observations'):compare_pair(good,bad)
        compare_pair(good,copy.deepcopy(good))

    def test_one_asset_value_cannot_be_hidden_by_opposite_other_asset(self):
        expected={'A':{'liability':'11'},'B':{'liability':'0.5'}}
        good={'ledgers':copy.deepcopy(expected)}
        bad={'ledgers':{'A':{'liability':'12'},'B':{'liability':'-0.5'}}}
        with self.assertRaisesRegex(AssertionError,'literal economic oracle'):quantities(bad,expected)
        quantities(good,expected)

    def test_unexpected_asset_cannot_pass_literal_oracle(self):
        expected={'A':{'liability':'11'}}
        with self.assertRaisesRegex(AssertionError,'exact asset set'):quantities({'ledgers':{'A':{'liability':'11'},'B':{'liability':'0'}}},expected)

    def test_changed_saved_canonical_export_rejected(self):
        good={'observations':{},'logical_before_reopen':{},'logical_after_reopen':{},'canonical_files':{'initial-canonical-run.json':'original'}}
        bad=copy.deepcopy(good);bad['canonical_files']['initial-canonical-run.json']='changed'
        with self.assertRaisesRegex(AssertionError,'canonical_files'):compare_pair(good,bad)

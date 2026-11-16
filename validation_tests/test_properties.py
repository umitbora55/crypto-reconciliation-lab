"""Independent checks of the new harness and real application boundaries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from validation_lab import properties as p


class FinitePropertyHarnessTests(unittest.TestCase):
    def test_integer_wire_oracle_known_literals(self):
        for units, places, text in ((1,8,'0.00000001'),(100,2,'1'),(-11,2,'-0.11'),(0,18,'0'),(123456,2,'1234.56')):
            self.assertEqual(p.quantity(units, places), text)
            self.assertEqual(p.integer_units(text, places), units)

    def test_baseline_and_declared_hard_negatives(self):
        with tempfile.TemporaryDirectory() as directory:
            w = p.world(29,3)
            for family in ('clean','missing_event','wrong_amount','same_version_conflict','replace_state_machine','void_state_machine'):
                with self.subTest(family=family):
                    result = p.execute(w,p.specification(w,family),directory)
                    self.assertEqual(result['status'],'PASS',result['errors'])

    def test_same_count_substitution_is_a_recorded_false_negative(self):
        with tempfile.TemporaryDirectory() as directory:
            w=p.world(47,1)
            result=p.execute(w,p.specification(w,'same_count_substitution'),directory)
            self.assertTrue(result['truth_anomaly'])
            self.assertFalse(result['alert'])
            self.assertEqual(p.confusion([result])['FN'],1)

    def test_mutation_harness_does_not_declare_survivors_killed(self):
        with tempfile.TemporaryDirectory() as directory:
            records=p.mutation_checks(directory)
        self.assertTrue(all(r['control']=='PASS' for r in records))
        self.assertTrue(any(r['killed'] for r in records))
        for r in records:
            self.assertEqual(r['classification'],'KILLED' if r['killed'] else 'SURVIVED')

    def test_confusion_matrix_literal_and_undefined_denominators(self):
        cases=[{'truth_anomaly':truth,'alert':alert} for truth,alert in ((True,True),(True,False),(False,True),(False,False))]
        result=p.confusion(cases)
        self.assertEqual([result[k] for k in ('TP','FP','TN','FN')],[1,1,1,1])
        self.assertEqual(result['recall'],.5)
        self.assertIsNone(p.confusion([])['precision'])

    def test_unmasked_quarantine_witness_kills_surviving_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = p.quarantine_followup(Path(directory) / 'witness')
        self.assertEqual(result['control']['status'], 'PASS')
        self.assertEqual(result['mutant']['status'], 'FAIL')
        self.assertTrue(result['killed'])

    def test_empty_or_duplicate_scope_cannot_report_success(self):
        for seeds in ((), (11,11), (-1,), (True,)):
            with self.subTest(seeds=seeds), self.assertRaises(ValueError):
                p.preregistration(seeds)

    def test_empty_duplicate_or_partial_family_roster_is_rejected(self):
        for roster in ((), ('clean','clean'), ('clean',)):
            with self.subTest(roster=roster), patch.object(p,'FAMILIES',roster), self.assertRaises(ValueError):
                p.preregistration((11,))

    def test_empty_duplicate_or_partial_factor_roster_is_rejected(self):
        for roster in ((), ((0,'external'),(0,'external')), ((0,'external'),)):
            with self.subTest(roster=roster), patch.object(p,'FACTORS',roster), self.assertRaises(ValueError):
                p.preregistration((11,))

    def test_broken_mutation_control_cannot_be_counted_as_kill(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(p,'execute',return_value={'status':'FAIL','errors':['injected broken baseline']}):
            records=p.mutation_checks(directory)
        self.assertTrue(all(r['control']=='FAIL' for r in records))
        self.assertFalse(any(r['killed'] for r in records))

if __name__=='__main__':
    unittest.main()

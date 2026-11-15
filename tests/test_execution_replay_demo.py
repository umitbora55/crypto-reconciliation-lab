"""Fixed public demonstration behavior, using independent literal expectations."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from crypto_reconciliation_lab.replay.demo import run_demo


class ExecutionReplayDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name) / 'demo'
        cls.summary = run_demo(cls.root)

    def result(self, name):
        return json.loads((self.root / 'commands' / name / 'result.json').read_bytes())

    def test_seven_real_cli_results_have_fixed_distinct_exit_semantics(self):
        self.assertEqual(self.summary['status'], 'PASS')
        self.assertEqual(self.summary['case_count'], 7)
        self.assertEqual([(row['id'], row['actual']['exit_code'], row['actual']['status']) for row in self.summary['cases']], [
            ('clean', 0, 'REPRODUCED'), ('custody_difference', 0, 'REPRODUCED'),
            ('old_cut_offline', 0, 'REPRODUCED'), ('wrong_identity', 2, 'ERROR'),
            ('numeric_divergence', 1, 'DIVERGED'), ('trace_divergence', 1, 'DIVERGED'),
            ('protected_recorded', 0, 'REPRODUCED')])
        for name in ('clean', 'custody_difference', 'protected_recorded'):
            self.assertEqual(self.result(name)['claims']['original_executable_identity'], 'NOT_RECORDED')
            self.assertEqual(self.result(name)['claims']['source_signature_verification'], 'NOT_PERFORMED')

    def test_genuine_financial_difference_remains_positive_one_while_reproducing(self):
        for part in ('saved', 'recomputed'):
            rows = self.result('custody_difference')['financial_summary'][part]['findings']
            amounts = {(row['comparison'], row['asset'], row['scope']):
                       (row['expected'], row['reported'], row['difference']) for row in rows}
            self.assertEqual(amounts, {('A', 'ASSET_A', 'I1'): ('7', '7', '0'),
                ('A', 'ASSET_A', 'I2'): ('4', '4', '0'), ('B', 'ASSET_A', 'customer_liability'): ('11', '10', '1'),
                ('A', 'ASSET_B', 'I1'): ('0.3', '0.3', '0'), ('A', 'ASSET_B', 'I2'): ('0.2', '0.2', '0'),
                ('B', 'ASSET_B', 'customer_liability'): ('0.5', '0.5', '0')})

    def test_old_cut_is_checked_after_all_source_databases_are_removed(self):
        lifecycle = self.summary['source_lifecycle']
        self.assertTrue(lifecycle['removed_before_cli'])
        self.assertEqual(len(lifecycle['created_databases']), 3)
        self.assertTrue(all(not Path(path).exists() for path in lifecycle['created_databases']))
        row = next(row for row in self.summary['cases'] if row['id'] == 'old_cut_offline')
        self.assertNotEqual(row['pin_observation']['run_id'], row['pin_observation']['later_run_id'])
        self.assertEqual(self.result('old_cut_offline')['comparison']['state'], 'EQUAL')
        self.assertFalse(list(self.root.rglob('*.sqlite3')))

    def test_hash_valid_numeric_and_trace_cases_reach_full_comparison(self):
        for name, pointer in [('numeric_divergence', '/ledgers/ASSET_A/liability'),
                              ('trace_divergence', '/ledgers/ASSET_A/trace/0/balances_after/I1')]:
            result = self.result(name)
            self.assertEqual(result['completion'], {'validation': 'COMPLETED', 'calculation': 'COMPLETED', 'comparison': 'COMPLETED'})
            self.assertIn(pointer, [row['path'] for row in result['comparison']['differences']])
            self.assertEqual(result['expected_execution_id'], result['derived_execution_id'])
            self.assertNotEqual(result['saved_canonical_run_id'], result['recomputed_canonical_run_id'])
        wrong = self.result('wrong_identity')
        self.assertEqual(wrong['reason_code'], 'REPLAY_INTEGRITY')
        self.assertEqual(wrong['completion']['calculation'], 'NOT_COMPLETED')

    def test_protected_resource_keeps_exact_genuine_0101_bytes_and_external_pin(self):
        row = next(row for row in self.summary['cases'] if row['id'] == 'protected_recorded')
        self.assertEqual(row['expected_execution_id'], 'b4ef410ef6066b2468a7049d8750aead659f7a889dd7087c006464cfe50ac0fd')
        self.assertEqual(row['inputs'], {
            'context': {'bytes': 138090, 'sha256': 'db18fa42e2f81140172745a3a6f993221d9d4f2462dad44615044c8a0efe099e'},
            'run': {'bytes': 36958, 'sha256': '14c675e3bdb3106451c069915db22095e9cacf26c1ab9e674b64d04754738dd0'}})
        self.assertEqual(row['pin_observation']['original_package'], '0.10.1')

    def test_existing_output_is_refused_without_clobbering(self):
        before = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'output already exists'):
            run_demo(self.root)
        self.assertEqual(before, {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in self.root.rglob('*') if p.is_file()})

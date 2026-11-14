"""Real child-crash acceptance and independent rejection controls for admission."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from crypto_reconciliation_lab.admission.recovery import run_recovery
from crypto_reconciliation_lab.admission.oracle import delivery_checks, negative_control, observed


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='admission-recovery-tests-')
        cls.root = Path(cls.temporary.name) / 'experiment'
        cls.summary = run_recovery(cls.root, seed=19)
        cls.cases = {r['id']: r for r in cls.summary['scenarios']}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_complete_predeclared_scenario_inventory(self):
        expected = ['clean', 'custody_difference', 'transport_replay', 'economic_duplicate',
                    'economic_conflict', 'transport_conflict', 'gap_recovery', 'invalid_payload',
                    'crash_after_record', 'crash_after_receipt', 'crash_after_disposition', 'lost_ack',
                    'ack_restart', 'writers_same_stream', 'writers_separate_stream', 'busy_retry',
                    'save_run_crash', 'changed_prefix', 'truncated_file', 'new_receipt_economic_parity',
                    'rejected_json']
        self.assertEqual(self.summary['planned_scenario_ids'], expected)
        self.assertEqual(self.summary['executed_scenario_ids'], expected)
        self.assertEqual(len(self.cases), len(expected))
        self.assertEqual(self.summary['status'], 'PASS', [(r['id'], r.get('error')) for r in self.cases.values() if r['status'] != 'PASS'])
        self.assertTrue(all(r['checks'] and all(c['passed'] for c in r['checks']) for r in self.cases.values()))
        self.assertEqual(self.summary['schedule_sha256'], hashlib.sha256((self.root / 'schedule.json').read_bytes()).hexdigest())

    def test_three_precommit_real_kills_leave_no_half_effect(self):
        for case, point in [('crash_after_record', 'ingest_before_receipt'),
                            ('crash_after_receipt', 'delivery_after_receipt'),
                            ('crash_after_disposition', 'delivery_before_commit')]:
            with self.subTest(case=case):
                row = self.cases[case]; process = row['processes'][0]
                self.assertEqual(process['barrier'], point)
                self.assertTrue(process['barrier_reached'])
                self.assertTrue(process['joined'])
                self.assertEqual(process['exit_code'], -9)
                self.assertEqual(process['sender_result'], 'UNKNOWN')
                self.assertTrue(next(c['passed'] for c in row['checks'] if c['name'] == 'precommit_all_core_and_transport_rollback'))
                self.assertEqual(row['observed']['core_receipts'], 30)

    def test_lost_ack_retries_original_receipt_and_result(self):
        row = self.cases['lost_ack']; process = row['processes'][0]
        self.assertEqual(process['barrier'], 'delivery_after_commit')
        self.assertEqual(process['exit_code'], -9)
        self.assertEqual(process['sender_result'], 'UNKNOWN')
        for name in ('unknown_retry_returns_original', 'unknown_retry_reuses_receipt_row', 'unknown_retry_is_replay'):
            self.assertTrue(next(c['passed'] for c in row['checks'] if c['name'] == name))
        self.assertEqual(row['observed']['core_receipts'], 30)
        self.assertEqual(row['status'], 'PASS')

    def test_transport_replay_and_new_economic_receipt_are_distinct(self):
        replay = self.cases['transport_replay']
        self.assertEqual(replay['observed']['attempt_outcomes'], {'COMMITTED': 30, 'REPLAY': 30})
        self.assertEqual(replay['observed']['core_receipts'], 30)
        self.assertTrue(next(c['passed'] for c in replay['checks'] if c['name'] == 'same_transport_replay_same_financial_payload_and_id'))
        changed = self.cases['new_receipt_economic_parity']
        self.assertEqual(changed['observed']['core_receipts'], 31)
        self.assertEqual(len(changed['observed']['run_ids']), 2)
        self.assertTrue(next(c['passed'] for c in changed['checks'] if c['name'] == 'new_receipt_changes_evidence_run_identity'))

    def test_blocked_and_changed_snapshots_never_create_financial_run(self):
        for case in ('transport_conflict', 'changed_prefix', 'truncated_file'):
            with self.subTest(case=case):
                row = self.cases[case]
                self.assertEqual(row['status'], 'PASS')
                self.assertEqual(row['financial']['status'], 'NOT_RUN')
                self.assertEqual(row['observed']['run_ids'], [])
                self.assertEqual(row['expected']['expected_terminal'], 'BLOCKED')
        self.assertEqual(self.cases['transport_conflict']['observed']['core_receipts'], 1)
        self.assertEqual(self.cases['truncated_file']['observed']['core_receipts'], 8)

    def test_core_conflict_invalid_and_frame_rejection_stay_visible(self):
        self.assertEqual(self.cases['economic_conflict']['observed']['core_statuses'], {'ACCEPTED': 30, 'CONFLICT': 1})
        self.assertEqual(self.cases['invalid_payload']['observed']['core_statuses'], {'ACCEPTED': 30, 'INVALID': 1})
        self.assertEqual(self.cases['rejected_json']['observed']['core_receipts'], 30)
        self.assertEqual(len(self.cases['rejected_json']['observed']['effect_identities']), 31)
        self.assertEqual(self.cases['rejected_json']['financial']['status'], 'NOT_RUN')

    def test_two_real_writers_and_busy_attempt_do_not_disappear(self):
        for case in ('writers_same_stream', 'writers_separate_stream'):
            processes = self.cases[case]['processes']
            self.assertEqual(len({p['pid'] for p in processes}), 2)
            self.assertTrue(all(p['joined'] and p['exit_code'] == 0 for p in processes))
        self.assertEqual(self.cases['writers_same_stream']['observed']['core_receipts'], 30)
        self.assertEqual(self.cases['writers_separate_stream']['observed']['core_receipts'], 60)
        busy = self.cases['busy_retry']
        response = next(p['result'] for p in busy['processes'] if p['result']['outcome'] == 'RETRYABLE_BUSY')
        self.assertFalse(response['ack'])
        self.assertFalse(response['durable'])
        self.assertIsNone(response['attempt_id'])
        self.assertEqual(busy['observed']['attempt_outcomes'], {'COMMITTED': 1, 'REPLAY': 1})

    def test_save_run_real_crash_preserves_old_history_and_retries_whole_run(self):
        row = self.cases['save_run_crash']
        self.assertEqual(row['processes'][0]['exit_code'], -9)
        self.assertEqual(row['processes'][0]['barrier'], 'save_before_commit')
        self.assertEqual(len(row['observed']['run_ids']), 2)
        for name in ('save_crash_all_run_tables_rollback', 'old_run_payload_preserved',
                     'corrected_group_count', 'corrected_effect_count', 'all_saved_finding_rows', 'all_saved_evidence_rows'):
            self.assertTrue(next(c['passed'] for c in row['checks'] if c['name'] == name))

    def test_oracle_rejects_wrong_first_bytes_and_broken_ack_models(self):
        control = negative_control()
        self.assertEqual(control['status'], 'EXPECTED_FAILURE')
        self.assertEqual({m['name'] for m in control['models']}, {'premature_ack', 'empty_cursor'})
        self.assertTrue(all(m['observed_status'] == 'FAIL' for m in control['models']))
        actual = observed(self.root / 'clean' / 'evidence.sqlite3')
        lines = (self.root / 'inputs' / 'clean.jsonl').read_bytes().splitlines(keepends=True)
        tampered = copy.deepcopy(actual)
        tampered['effects'][0]['payload'] = b'changed\n'
        checks = delivery_checks(tampered, {'feed': lines}, receipt_count=30, record_count=30, core_statuses={'ACCEPTED': 30})
        self.assertFalse(next(c['passed'] for c in checks if c['name'] == 'first_payload_exact_bytes_and_hash'))

    def test_existing_output_is_not_overwritten(self):
        before = (self.root / 'schedule.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'new directory'):
            run_recovery(self.root)
        self.assertEqual((self.root / 'schedule.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()

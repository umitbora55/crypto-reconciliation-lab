"""S9-F2 regressions using actual finite runs, never claimed process fixtures."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from crypto_reconciliation_lab.admission import recovery
from crypto_reconciliation_lab.demo import fixtures

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('semantic_release_gate', ROOT / 'scripts/release_admission_scope.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class AdmissionSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='admission-semantics-')
        cls.folder = Path(cls.tmp.name)
        cls.report = recovery.run_recovery(cls.folder / 'real', seed=19)
        cls.scope = gate.load_scope(ROOT)
        cls.schedule_hash = hashlib.sha256((cls.folder / 'real/schedule.json').read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def validate(self, report):
        return gate.validate_report(report, self.scope, schedule_sha256=self.schedule_hash)

    def row(self, report, name):
        return next(row for row in report['scenarios'] if row['id'] == name)

    def test_actual_complete_run_passes_semantic_gate(self):
        self.assertEqual(self.validate(self.report)['executed_count'], 21)

    def test_21_names_with_one_generic_check_cannot_replace_evidence(self):
        report = copy.deepcopy(self.report)
        for row in report['scenarios']:
            for field in ('financial', 'observed', 'responses'):
                row.pop(field, None)
            row['checks'] = [{'name': 'generic_ok', 'actual': True, 'expected': True, 'passed': True}]
        with self.assertRaisesRegex(ValueError, 'ADMISSION_SCOPE'):
            self.validate(report)

    def test_real_clean_case_cannot_skip_financial_work_by_plan(self):
        item = copy.deepcopy(self.row(self.report, 'clean')['expected'])
        item['financial_projection'] = 'NOT_RUN'
        folder = self.folder / 'omitted-financial'; folder.mkdir()
        config, _, _ = fixtures('clean')
        try:
            row = recovery._case('clean', folder, config, self.folder / 'real/inputs/clean.jsonl', item)
        except ValueError as exc:
            self.assertIn('ADMISSION_SCOPE', str(exc))
            return
        with sqlite3.connect(folder / 'evidence.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
        report = copy.deepcopy(self.report)
        report['scenarios'][0] = row
        with self.assertRaisesRegex(ValueError, 'ADMISSION_SCOPE'):
            self.validate(report)

    def test_stale_passed_flag_cannot_hide_lost_ack_committed_result(self):
        report = copy.deepcopy(self.report)
        row = self.row(report, 'lost_ack')
        target = next(c for c in row['checks'] if c['name'] == 'unknown_retry_is_replay')
        target.update(actual='COMMITTED', expected='REPLAY', passed=True)
        with self.assertRaisesRegex(ValueError, 'ADMISSION_SCOPE'):
            self.validate(report)

    def test_required_control_missing_duplicate_or_substituted_is_rejected(self):
        for mode in ('missing', 'duplicate', 'substituted'):
            report = copy.deepcopy(self.report)
            row = self.row(report, 'clean')
            index = next(i for i,c in enumerate(row['checks']) if c['name'] == 'effect_core_receipt_result_links')
            if mode == 'missing': row['checks'].pop(index)
            elif mode == 'duplicate': row['checks'].append(copy.deepcopy(row['checks'][index]))
            else: row['checks'][index]['name'] = 'substitute_same_count'
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'ADMISSION_SCOPE'):
                self.validate(report)

    def test_process_proof_requires_pid_join_and_matching_observed_barrier(self):
        mutations = ('missing_pid','missing_join','missing_messages','wrong_ready_pid','wrong_barrier_pid','wrong_point')
        for mode in mutations:
            report = copy.deepcopy(self.report)
            p = self.row(report,'lost_ack')['processes'][0]
            if mode == 'missing_pid': p.pop('pid')
            elif mode == 'missing_join': p.pop('joined')
            elif mode == 'missing_messages': p.pop('messages')
            elif mode == 'wrong_ready_pid': p['ready']['pid'] += 1
            else:
                barrier = next(m for m in p['messages'] if m.get('type')=='BARRIER')
                if mode == 'wrong_barrier_pid': barrier['pid'] += 1
                else: barrier['point'] = 'wrong_barrier'
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'ADMISSION_SCOPE'):
                self.validate(report)

    def test_negative_models_need_actual_rejected_invariants(self):
        for mode in ('missing_checks','empty_rejections','labels_only'):
            report = copy.deepcopy(self.report)
            negative = report['negative_control']
            if mode == 'missing_checks': negative.pop('checks')
            elif mode == 'empty_rejections':
                negative['rejected_checks'] = []
                for model in negative['models']: model['rejected_checks'] = []
            else:
                report['negative_control'] = {'status':'EXPECTED_FAILURE','models':[
                    {'name':m['name'],'observed_status':'FAIL'} for m in negative['models']]}
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError,'ADMISSION_SCOPE'):
                self.validate(report)

    def test_required_and_forbidden_financial_work_is_independent_of_flags(self):
        for name in ('clean', 'transport_conflict', 'busy_retry'):
            report = copy.deepcopy(self.report)
            row = self.row(report,name)
            if name == 'clean':
                row['financial'] = {'status':'NOT_RUN','reason':'omitted'}
                row['observed']['run_ids'] = []
                row['observed']['run_payload_hashes'] = {}
            else:
                row['observed']['run_ids'] = ['a'*64]
                row['observed']['run_payload_hashes'] = {'a'*64:'b'*64}
            with self.subTest(name=name), self.assertRaisesRegex(ValueError,'ADMISSION_SCOPE'):
                self.validate(report)

    def test_required_observation_and_response_subfields_cannot_disappear(self):
        mutations = [('clean','observed','effect_identities'),('clean','financial','findings'),
                     ('lost_ack','responses',None),('crash_after_record','observed','core_receipts')]
        for name,field,key in mutations:
            report=copy.deepcopy(self.report); row=self.row(report,name)
            if key is None: row[field]=[]
            else: row[field].pop(key)
            with self.subTest(name=name,field=field,key=key), self.assertRaisesRegex(ValueError,'ADMISSION_SCOPE'):
                self.validate(report)


if __name__ == '__main__':
    unittest.main()

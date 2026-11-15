"""The release gate rejects incomplete or coherently mislabeled replay evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import crypto_reconciliation_lab as package
from crypto_reconciliation_lab.replay.demo import run_demo

SPEC = importlib.util.spec_from_file_location('replay_release_test_helper',
    Path(__file__).resolve().parents[1] / 'scripts/release_execution_replay.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def encode(row):
    return (json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()


class ExecutionReplayReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.original = Path(cls.temp.name) / 'original'
        result = run_demo(cls.original)
        if result['status'] != 'PASS':
            raise AssertionError(result)

    def setUp(self):
        # Actual command argv binds the original location. Restore it after each
        # test; do not silently rewrite historical command paths for copies.
        self.backup = Path(self.temp.name) / self._testMethodName
        shutil.copytree(self.original, self.backup)
        self.addCleanup(self.restore)

    def restore(self):
        shutil.rmtree(self.original)
        shutil.copytree(self.backup, self.original)

    def check(self):
        return GATE.validate_demo(self.original, package_origin=package.__file__, executable=sys.executable,
                                  isolated=bool(sys.flags.isolated), cwd=Path.cwd())

    def summary(self):
        return json.loads((self.original / 'summary.json').read_bytes())

    def save_summary(self, value):
        (self.original / 'summary.json').write_bytes(encode(value))

    def coherent_result(self, name, mutate):
        root = self.original / 'commands' / name
        result = json.loads((root / 'result.json').read_bytes()); mutate(result)
        raw = encode(result); (root / 'result.json').write_bytes(raw); (root / 'stdout.txt').write_bytes(raw)
        command = json.loads((root / 'command.json').read_bytes())
        command['stdout'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        command_raw = encode(command); (root / 'command.json').write_bytes(command_raw)
        summary = self.summary(); row = next(row for row in summary['cases'] if row['id'] == name)
        row['result_identity'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        row['command_identity'] = {'bytes': len(command_raw), 'sha256': hashlib.sha256(command_raw).hexdigest()}
        self.save_summary(summary)

    def test_complete_actual_seven_case_demo_passes(self):
        self.assertEqual(self.check()['case_ids'], ['clean', 'custody_difference', 'old_cut_offline',
            'wrong_identity', 'numeric_divergence', 'trace_divergence', 'protected_recorded'])

    def test_missing_case_cannot_be_hidden_by_smaller_reported_count(self):
        row = self.summary(); row['cases'].pop(); row['case_count'] = 6; self.save_summary(row)
        with self.assertRaisesRegex(ValueError, 'seven cases'):
            self.check()

    def test_duplicate_case_cannot_replace_required_semantic_control(self):
        row = self.summary(); row['cases'][-1] = copy.deepcopy(row['cases'][0]); self.save_summary(row)
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.check()

    def test_missing_catalog_is_rejected(self):
        (self.original / 'catalog.json').unlink()
        with self.assertRaisesRegex(ValueError, 'missing or unsafe'):
            self.check()

    def test_changed_actual_cli_log_is_rejected(self):
        (self.original / 'commands/clean/stdout.txt').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'log identity'):
            self.check()

    def test_rehashed_wrong_semantic_reason_is_rejected(self):
        self.coherent_result('numeric_divergence', lambda row: row.update(reason_code='REPLAY_INTEGRITY'))
        with self.assertRaisesRegex(ValueError, 'report result'):
            self.check()

    def test_rehashed_missing_trace_comparison_witness_is_rejected(self):
        self.coherent_result('trace_divergence', lambda row: row['comparison'].update(differences=[]))
        with self.assertRaisesRegex(ValueError, 'semantic comparison witness'):
            self.check()

    def test_rehashed_invented_original_executable_claim_is_rejected(self):
        self.coherent_result('clean', lambda row: row['claims'].update(original_executable_identity='VERIFIED'))
        with self.assertRaisesRegex(ValueError, 'claims'):
            self.check()

    def test_rehashed_wrong_literal_financial_difference_is_rejected(self):
        def mutate(row):
            row['financial_summary']['recomputed']['findings'][2]['difference'] = '0'
        self.coherent_result('custody_difference', mutate)
        with self.assertRaisesRegex(ValueError, 'literal amounts'):
            self.check()


class ExecutionReplayTimeoutGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'test_real_blocked_child_hits_deadline_is_killed_and_reaped/observation.json'
        self.path.parent.mkdir()
        # Hand-authored transcript tests gate semantics, not an actual process claim.
        self.row = {'interpreter': '/test/python', 'isolated': True, 'returncode': -9, 'duration_seconds': 1.2,
                    'child': {'pid': 123, 'mode': 'hang', 'argv': ['test-worker'], 'cwd': '/test'},
                    'result': {'status': 'ERROR', 'exit_code': 2, 'reason_code': 'REPLAY_TIMEOUT',
                               'completion': {'calculation': 'NOT_COMPLETED'}}}

    def check(self):
        self.path.write_bytes(encode(self.row))
        return GATE.validate_timeout(self.root, executable='/test/python', isolated=True)

    def test_hand_authored_complete_timeout_transcript_is_accepted(self):
        self.assertEqual(self.check()['returncode'], -9)

    def test_exited_or_unreaped_child_is_rejected(self):
        for code in (0, None, 9):
            with self.subTest(code=code):
                self.row['returncode'] = code
                with self.assertRaisesRegex(ValueError, 'killed and reaped'):
                    self.check()

    def test_non_timeout_failure_cannot_replace_timeout_coverage(self):
        self.row['result']['reason_code'] = 'REPLAY_LIMIT'
        with self.assertRaisesRegex(ValueError, 'killed and reaped'):
            self.check()

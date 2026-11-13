"""Reject provisional completion and preserve known failure in external proofs."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/measure_stage3_3.py'
SPEC = importlib.util.spec_from_file_location('stage3_3_execution', SCRIPT)
launch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launch)


class ExecutionProofTests(unittest.TestCase):
    def proof(self):
        return dict(exit_code=0, source_and_installed_preserved=True,
            terminal_outcome=dict(status='COMPLETED', correctness='PASSED', completion_state='COMPLETED', shared_deadline_met=True),
            finalization_receipt=dict(status='COMPLETED', verified=True, shared_deadline_met=True,
                report_sha256='a' * 64, markdown_sha256='b' * 64))

    def test_completion_requires_actual_exit_deadline_and_bound_artifacts(self):
        self.assertTrue(launch.complete_binding(self.proof(), 'a' * 64, 'b' * 64))
        for field, value in [('exit_code', 4), ('source_and_installed_preserved', False), ('finalization_receipt', None)]:
            with self.subTest(field=field):
                proof = self.proof(); proof[field] = value
                self.assertFalse(launch.complete_binding(proof, 'a' * 64, 'b' * 64))
        proof = self.proof(); proof['terminal_outcome']['shared_deadline_met'] = False
        self.assertFalse(launch.complete_binding(proof, 'a' * 64, 'b' * 64))
        self.assertFalse(launch.complete_binding(self.proof(), 'c' * 64, 'b' * 64))

    def test_missing_or_malformed_hashes_cannot_bind_a_receipt(self):
        for value in (None, '', 'z' * 64):
            with self.subTest(value=value):
                proof = self.proof(); proof['finalization_receipt']['report_sha256'] = value
                self.assertFalse(launch.complete_binding(proof, value, 'b' * 64))

    def test_known_failed_controller_survives_later_origin_audit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); docs = root / 'docs'; docs.mkdir()
            (docs / 'verification.json').write_text(json.dumps(dict(status='PASS', frozen_build_fingerprint='candidate')))
            (docs / 'baseline.json').write_text(json.dumps(dict(status='PASS', matrix=dict(build_fingerprint='baseline'))))
            (docs / 'migration_verification.json').write_text('{"status":"COMPLETED","verified":true,"build_fingerprint":"candidate"}')
            terminal = dict(version='stage3.3-terminal-v1', status='CORRECTNESS_FAILED',
                correctness='FAILED', completion_state='ERROR')
            child = SimpleNamespace(returncode=3, stdout=json.dumps(terminal) + '\n', stderr='controlled')
            proof = docs / 'ab_execution.json'
            with patch.multiple(launch, ROOT=root, DOCS=docs, OUT=root / 'ab', PROOF=proof), \
                    patch.object(launch, 'origin_manifest', side_effect=[{}, OSError('controlled post-run audit failure')]), \
                    patch.object(launch.subprocess, 'run', return_value=child):
                with self.assertRaisesRegex(OSError, 'controlled post-run'):
                    launch.main()
            saved = json.loads(proof.read_text())
            self.assertEqual((saved['status'], saved['correctness'], saved['exit_code']), ('CORRECTNESS_FAILED', 'FAILED', 3))
            self.assertFalse(saved['complete_claim_verified'])

    def test_detected_origin_drift_survives_a_report_write_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); docs = root / 'docs'; docs.mkdir()
            (docs / 'verification.json').write_text(json.dumps(dict(status='PASS', frozen_build_fingerprint='candidate')))
            (docs / 'baseline.json').write_text(json.dumps(dict(status='PASS', matrix=dict(build_fingerprint='baseline'))))
            (docs / 'migration_verification.json').write_text('{"status":"COMPLETED","verified":true,"build_fingerprint":"candidate"}')
            terminal = dict(version='stage3.3-terminal-v1', status='COMPLETED',
                correctness='PASSED', completion_state='COMPLETED')
            child = SimpleNamespace(returncode=0, stdout=json.dumps(terminal) + '\n', stderr='')
            proof = docs / 'ab_execution.json'
            original_write = Path.write_text
            failures = []
            def write(path, text, *args, **kwargs):
                if path == proof and json.loads(text).get('status') == 'CORRECTNESS_FAILED' and not failures:
                    failures.append(True)
                    raise OSError('controlled proof write failure')
                return original_write(path, text, *args, **kwargs)
            with patch.multiple(launch, ROOT=root, DOCS=docs, OUT=root / 'ab', PROOF=proof), \
                    patch.object(launch, 'origin_manifest', side_effect=[{}, {'changed': True}]), \
                    patch.object(launch.subprocess, 'run', return_value=child), patch.object(Path, 'write_text', write):
                with self.assertRaisesRegex(OSError, 'controlled proof write'):
                    launch.main()
            saved = json.loads(proof.read_text())
            self.assertEqual((saved['status'], saved['correctness']), ('CORRECTNESS_FAILED', 'FAILED'))
            self.assertFalse(saved['source_and_installed_preserved'])


if __name__ == '__main__':
    unittest.main()

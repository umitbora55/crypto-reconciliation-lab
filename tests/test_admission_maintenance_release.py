"""The authorized fixture rewrite must not become permission to weaken old tests."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('maintenance_release_scope', ROOT / 'scripts/release_test_scope.py')
scope_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope_gate)


class AdmissionMaintenanceReleaseTests(unittest.TestCase):
    def fixture_exception(self):
        scope = scope_gate.checked_document(ROOT, scope_gate.BASELINE_PATH, scope_gate.BASELINE_BYTES, scope_gate.BASELINE_SHA256)
        return deepcopy(next(row for row in scope['fixture_exceptions']
                             if row.get('kind') == 'report-fixture-function-v1'))

    def test_named_fixture_permission_cannot_hide_a_changed_old_assertion(self):
        exception = self.fixture_exception()
        current = (ROOT / exception['path']).read_bytes()
        scope_gate.restore_fixture_source(current, exception)
        original = b"self.assertEqual(self.validate(self.report)['executed_count'], 21)"
        self.assertEqual(current.count(original), 1)
        changed = current.replace(original, original.replace(b'21)', b'20)'), 1)
        # Even a caller claiming the new full-file digest cannot widen the block.
        exception['current'] = scope_gate.byte_identity(changed)
        with self.assertRaisesRegex(ValueError, 'exceeds authorized expressions'):
            scope_gate.restore_fixture_source(changed, exception)

    def test_named_fixture_permission_rejects_other_targets_and_extra_code(self):
        for change in ('path', 'function', 'extra_statement'):
            exception = self.fixture_exception()
            if change == 'path':
                exception['path'] = 'tests/test_admission_recovery.py'
            elif change == 'function':
                exception['function'] = 'test_lost_ack_retries_original_receipt_and_result'
            else:
                exception['changes'][0]['new_text'] += '\nUNAUTHORIZED_ASSERTION_OVERRIDE = True\n'
                exception['current_block'] = scope_gate.byte_identity(exception['changes'][0]['new_text'].encode())
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'TEST_SCOPE'):
                scope_gate.validate_fixture_exception(exception)

    def test_other_metadata_permissions_still_reject_multiline_replacements(self):
        scope = scope_gate.load_test_scope(ROOT)
        exception = deepcopy(next(row for row in scope['fixture_exceptions']
                                  if row.get('kind', 'metadata-lines-v1') == 'metadata-lines-v1'))
        exception['changes'][0]['new_text'] += '\nUNAUTHORIZED_ASSERTION_OVERRIDE = True'
        with self.assertRaisesRegex(ValueError, 'single-line metadata replacement'):
            scope_gate.validate_fixture_exception(exception)

    def test_wheel_allows_only_the_named_recovery_scope_json_asset(self):
        spec = importlib.util.spec_from_file_location('maintenance_release', ROOT / 'scripts/verify_release.py')
        verifier = importlib.util.module_from_spec(spec); spec.loader.exec_module(verifier)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = 'crypto_reconciliation_lab/admission/recovery_scope_v2.json'
            for name in (allowed, 'crypto_reconciliation_lab/admission/unreviewed.json'):
                path = root / (Path(name).stem + '.whl')
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr(name, '{}\n')
                if name == allowed:
                    self.assertEqual(set(verifier.wheel_manifest(path)), {allowed})
                else:
                    with self.assertRaisesRegex(ValueError, 'unexpected package data'):
                        verifier.wheel_manifest(path)


if __name__ == '__main__':
    unittest.main()

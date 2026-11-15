"""Maintenance scope retains the reviewed 729 identities and bounded fixtures."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('maintenance_scope', ROOT / 'scripts/release_test_scope.py')
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)


class ExecutionMaintenanceScopeTests(unittest.TestCase):
    def test_reviewed_execution_anchor_retains_exact_bytes_and_identities(self):
        raw = (ROOT / 'contracts/release-test-scope-0.10.0.json').read_bytes()
        self.assertEqual(len(raw), 186212)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '80ab84b011000db8b710b267e850963ec2da0a15063ee516896f14119d5ef8ec')
        previous = json.loads(raw)
        current = scope.load_test_scope(ROOT)
        self.assertEqual(len(set(previous['current']['test_ids'])), 729)
        self.assertLessEqual(set(previous['current']['test_ids']), set(current['current']['test_ids']))
        self.assertEqual(scope.EXECUTION_PATH, 'contracts/release-test-scope-0.10.0.json')
        self.assertEqual(scope.MAINTENANCE_PATH, 'contracts/release-test-scope-0.9.1.json')

    def test_only_three_old_files_have_exact_reversible_maintenance_edits(self):
        current = scope.load_test_scope(ROOT)
        previous = json.loads((ROOT / scope.EXECUTION_PATH).read_bytes())
        exceptions = current['execution_release']['fixture_exceptions']
        self.assertEqual({row['path'] for row in exceptions}, {
            'tests/test_release_test_scope.py', 'tests/test_provenance_maintenance_release.py',
            'tests/test_recorded_execution_release_gate.py'})
        for row in exceptions:
            with self.subTest(path=row['path']):
                scope.validate_execution_repair_fixture_exception(row)
                restored = scope.restore_fixture_source((ROOT / row['path']).read_bytes(), row)
                self.assertEqual(scope.byte_identity(restored), previous['current']['files'][row['path']])

    def test_process_fixture_permission_rejects_other_methods_paths_and_unpinned_bodies(self):
        current = scope.load_test_scope(ROOT)
        original = next(row for row in current['execution_release']['fixture_exceptions']
                        if row['path'] == 'tests/test_recorded_execution_release_gate.py')
        for kind in ('path', 'surrounding_method', 'same_signature_unpinned_body', 'lost_helper'):
            changed = deepcopy(original)
            if kind == 'path':
                changed['path'] = 'tests/test_recorded_execution_processes.py'
            elif kind == 'surrounding_method':
                changed['changes'][0]['new_text'] += '\ndef test_no_longer_checked():\n    pass\n'
            elif kind == 'same_signature_unpinned_body':
                changed['changes'][0]['new_text'] += '\n'
            else:
                changed['changes'].pop()
            with self.subTest(mutation=kind), self.assertRaisesRegex(ValueError, 'TEST_SCOPE:'):
                scope.validate_execution_repair_fixture_exception(changed)

    def test_version_exception_cannot_be_extended_to_financial_or_schema_assertions(self):
        current = scope.load_test_scope(ROOT)
        original = next(row for row in current['execution_release']['fixture_exceptions']
                        if row['path'] == 'tests/test_release_test_scope.py')
        for old, new in (("self.assertEqual(balance, '7')", "self.assertEqual(balance, '8')"),
                         ('self.assertEqual(schema, 6)', 'self.assertEqual(schema, 7)')):
            changed = deepcopy(original)
            changed['changes'].append({'old_text': old, 'new_text': new, 'count': 1})
            with self.subTest(expression=old), self.assertRaisesRegex(ValueError, 'TEST_SCOPE:'):
                scope.validate_execution_repair_fixture_exception(changed)


if __name__ == '__main__':
    unittest.main()

"""Finite release preservation permissions for additive recorded execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('execution_scope_gate', ROOT / 'scripts/release_test_scope.py')
scope = importlib.util.module_from_spec(spec); spec.loader.exec_module(scope)


class RecordedExecutionScopeTests(unittest.TestCase):
    def test_accepted_661_identity_anchor_remains_byte_pinned(self):
        self.assertEqual(scope.MAINTENANCE_PATH, 'contracts/release-test-scope-0.9.1.json')
        raw = (ROOT / scope.MAINTENANCE_PATH).read_bytes()
        self.assertEqual(len(raw), 123752)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '6f67d9217776dfe34a8e2f975cbe58c7e2b39eb4f310b78165973b2aa5d81118')
        self.assertEqual(len(set(json.loads(raw)['current']['test_ids'])), 661)
        self.assertEqual(scope.PROVENANCE_PATH, 'contracts/release-test-scope-0.9.0.json')
        self.assertEqual(scope.BASELINE_PATH, 'contracts/release-test-scope-0.7.1.json')

    def test_real_schema_five_setup_is_fixed_and_cannot_override_an_assertion(self):
        name = 'tests/test_provenance_verifier.py'
        exception = {'path': name, 'kind': 'schema5-history-setup-v1', 'changes': [
            {'old_text': '        store = Store(database, CONFIG)',
             'new_text': '        store = Store(database, CONFIG, target_schema=5)', 'count': 1}]}
        scope.validate_execution_fixture_exception(exception)
        for mutation in ('future_schema', 'assertion', 'other_path'):
            changed = deepcopy(exception)
            if mutation == 'future_schema':
                changed['changes'][0]['new_text'] = changed['changes'][0]['new_text'].replace('=5', '=6')
            elif mutation == 'assertion':
                changed['changes'][0]['new_text'] += '\n        self.assertTrue(True)'
            else:
                changed['path'] = 'tests/test_corrections.py'
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'fixed metadata/setup'):
                scope.validate_execution_fixture_exception(changed)

    def test_version_metadata_permission_cannot_change_financial_assertion(self):
        exception = {'path': 'tests/test_corrections.py', 'kind': 'metadata-lines-v1', 'changes': [
            {'old_text': "        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)",
             'new_text': "        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)", 'count': 1}]}
        scope.validate_execution_fixture_exception(exception)
        changed = deepcopy(exception)
        changed['changes'][0] = {'old_text': "self.assertEqual(balance, '7')",
                                 'new_text': "self.assertEqual(balance, '8')", 'count': 1}
        with self.assertRaisesRegex(ValueError, 'fixed metadata/setup'):
            scope.validate_execution_fixture_exception(changed)

    def test_every_changed_old_fixture_reverses_to_accepted_bytes(self):
        contract = scope.load_test_scope(ROOT)
        binding = contract['maintenance_release']
        self.assertEqual(binding['path'], scope.MAINTENANCE_PATH)
        accepted = json.loads((ROOT / scope.MAINTENANCE_PATH).read_bytes())
        self.assertLessEqual(set(accepted['current']['test_ids']), set(contract['current']['test_ids']))
        self.assertEqual({item['path'] for item in binding['fixture_exceptions']}, scope.EXECUTION_FIXTURE_PATHS)
        for exception in binding['fixture_exceptions']:
            with self.subTest(path=exception['path']):
                scope.validate_execution_fixture_exception(exception)
                restored = scope.restore_fixture_source((ROOT / exception['path']).read_bytes(), exception)
                self.assertEqual(scope.byte_identity(restored), accepted['current']['files'][exception['path']])


if __name__ == '__main__':
    unittest.main()

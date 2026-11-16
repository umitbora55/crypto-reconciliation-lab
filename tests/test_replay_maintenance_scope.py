"""Independent exact preservation limits for the two Stage13.1 repairs."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('replay_repair_scope', ROOT / 'scripts/release_test_scope.py')
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)
ANCHOR = 'contracts/release-test-scope-0.11.0.json'
EXACT_EDITS = {
    'tests/test_release_test_scope.py': [
        ("CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'", "CONTRACT_PATH = 'contracts/release-test-scope-0.11.1.json'"),
        ("                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.0'}",
         "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.1'}"),
    ],
    'tests/test_provenance_maintenance_release.py': [
        ("    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.0',",
         "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.1',"),
    ],
    'tests/test_execution_replay_scope.py': [
        ('"CONTRACT_PATH = \'contracts/release-test-scope-0.11.0.json\'"',
         '"CONTRACT_PATH = \'contracts/release-test-scope-0.11.1.json\'"'),
        ('"                 \'sha256\':hashlib.sha256(current.read_bytes()).hexdigest(), \'release\':\'0.11.0\'}"',
         '"                 \'sha256\':hashlib.sha256(current.read_bytes()).hexdigest(), \'release\':\'0.11.1\'}"'),
        ('"    setup = {\'format\': \'release-provenance-maintenance-v1\', \'package_version\': \'0.11.0\',"',
         '"    setup = {\'format\': \'release-provenance-maintenance-v1\', \'package_version\': \'0.11.1\',"'),
    ],
}


def methods(raw):
    return [ast.dump(node, include_attributes=False) for node in ast.walk(ast.parse(raw))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test')]


class ReplayMaintenanceScopeTests(unittest.TestCase):
    def test_reviewed_858_identity_anchor_has_exact_independent_bytes(self):
        raw = (ROOT / ANCHOR).read_bytes()
        self.assertEqual(len(raw), 245263)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '3bbd2f2252947c90395f69161849ce790fc183a80f3ecf63075d48b18080cdb1')
        previous, current = json.loads(raw), scope.load_test_scope(ROOT)
        self.assertEqual(previous['current']['file_count'], 89)
        self.assertEqual(len(set(previous['current']['test_ids'])), 858)
        self.assertLessEqual(set(previous['current']['test_ids']), set(current['current']['test_ids']))
        self.assertEqual(scope.REPLAY_PATH, ANCHOR)
        self.assertEqual(scope.EXECUTION_REPAIR_PATH, 'contracts/release-test-scope-0.10.1.json')

    def test_six_literal_changes_restore_all_previous_bytes_and_test_methods(self):
        previous = json.loads((ROOT / ANCHOR).read_bytes())
        current = scope.load_test_scope(ROOT)
        rows = current['replay_release']['fixture_exceptions']
        self.assertEqual({row['path'] for row in rows}, set(EXACT_EDITS))
        self.assertEqual(sum(len(row['changes']) for row in rows), 6)
        for row in rows:
            with self.subTest(path=row['path']):
                self.assertEqual(row['changes'], [dict(old_text=a, new_text=b, count=1)
                                                 for a, b in EXACT_EDITS[row['path']]])
                raw = scope.restore_gate2_fixture_source(ROOT, row['path'], (ROOT / row['path']).read_bytes())
                restored = scope.restore_fixture_source(raw, row)
                self.assertEqual(scope.byte_identity(restored), previous['current']['files'][row['path']])
                self.assertEqual(methods(restored), methods(raw))
        for name, expected in previous['current']['files'].items():
            if name not in EXACT_EDITS:
                with self.subTest(unchanged=name):
                    self.assertEqual(scope.byte_identity(scope.restore_gate2_fixture_source(ROOT, name, (ROOT / name).read_bytes())), expected)

    def test_composition_preserves_originals_paths_process_pins_and_old_negative(self):
        previous = json.loads((ROOT / ANCHOR).read_bytes())
        current = scope.load_test_scope(ROOT)
        replacements = dict(pair for name, edits in EXACT_EDITS.items()
                            if name != 'tests/test_execution_replay_scope.py' for pair in edits)
        for name in ('previous_release', 'reviewed_release', 'accepted_release', 'provenance_release',
                     'maintenance_release', 'execution_release', 'execution_repair_release'):
            old, new = previous[name], current[name]
            self.assertEqual({k: new[k] for k in ('path', 'bytes', 'sha256')},
                             {k: old[k] for k in ('path', 'bytes', 'sha256')})
            self.assertEqual([row['path'] for row in new['fixture_exceptions']],
                             [row['path'] for row in old['fixture_exceptions']])
            for before, after in zip(old['fixture_exceptions'], new['fixture_exceptions']):
                with self.subTest(binding=name, path=before['path']):
                    self.assertEqual(after['original'], before['original'])
                    self.assertEqual(after.get('kind'), before.get('kind'))
                    self.assertEqual(after['changes'], [dict(edit, new_text=replacements.get(edit['new_text'], edit['new_text']))
                                                       for edit in before['changes']])
                    self.assertEqual(scope.byte_identity(scope.restore_fixture_source((ROOT / after['path']).read_bytes(), after)),
                                     before['original'])
        rows = current['execution_repair_release']['fixture_exceptions']
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(len(row['changes']) for row in rows), 3)
        self.assertIn("dict(old_text='0.10.1', new_text='0.11.0', count=1)",
                      (ROOT / 'tests/test_execution_replay_scope.py').read_text())

    def test_permission_rejects_new_paths_behavior_and_generic_version_changes(self):
        current = scope.load_test_scope(ROOT)
        original = next(row for row in current['replay_release']['fixture_exceptions']
                        if row['path'] == 'tests/test_execution_replay_scope.py')
        for mutation in ('path', 'behavior', 'old_endpoint', 'regex', 'boolean_count'):
            changed = deepcopy(original)
            if mutation == 'path':
                changed['path'] = 'tests/replay_historical_fixtures.py'
            elif mutation == 'behavior':
                changed['changes'].append(dict(old_text='self.assertEqual(value, 1)', new_text='self.assertEqual(value, 2)', count=1))
            elif mutation == 'old_endpoint':
                changed['changes'][0]['old_text'] = '0.10.1'
            elif mutation == 'regex':
                changed['changes'][0] = dict(old_text='0.11.0', new_text='0.11.1', count=1)
            else:
                changed['changes'][0]['count'] = True
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'TEST_SCOPE:'):
                scope.validate_replay_repair_fixture_exception(changed)


if __name__ == '__main__':
    unittest.main()

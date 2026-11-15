"""Independent preservation checks for Stage13's three metadata permissions."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('replay_scope', ROOT / 'scripts/release_test_scope.py')
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)

ANCHOR = 'contracts/release-test-scope-0.10.1.json'
EXACT_EDITS = {
    'tests/test_release_test_scope.py': [
        ("CONTRACT_PATH = 'contracts/release-test-scope-0.10.1.json'", "CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'"),
        ("                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.10.1'}",
         "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.0'}"),
    ],
    'tests/test_provenance_maintenance_release.py': [
        ("    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.10.1',",
         "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.0',"),
    ],
}


class ReplayReleaseScopeTests(unittest.TestCase):
    def test_accepted_778_identity_anchor_has_exact_independent_bytes(self):
        raw = (ROOT / ANCHOR).read_bytes()
        self.assertEqual(len(raw), 219024)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '2ac30fd8f96a5223b174b899484b72aaad2982c64de6c168b34670c419aa8427')
        previous, current = json.loads(raw), scope.load_test_scope(ROOT)
        self.assertEqual(previous['current']['file_count'], 78)
        self.assertEqual(len(set(previous['current']['test_ids'])), 778)
        self.assertLessEqual(set(previous['current']['test_ids']), set(current['current']['test_ids']))
        self.assertEqual(scope.EXECUTION_REPAIR_PATH, ANCHOR)
        self.assertEqual(scope.EXECUTION_PATH, 'contracts/release-test-scope-0.10.0.json')
        self.assertEqual(scope.MAINTENANCE_PATH, 'contracts/release-test-scope-0.9.1.json')

    def test_current_metadata_permission_is_exact_and_reverses_every_old_byte(self):
        previous = json.loads((ROOT / ANCHOR).read_bytes())
        current = scope.load_test_scope(ROOT)
        rows = current['execution_repair_release']['fixture_exceptions']
        self.assertEqual({row['path'] for row in rows}, set(EXACT_EDITS))
        self.assertEqual(sum(len(row['changes']) for row in rows), 3)
        for row in rows:
            with self.subTest(path=row['path']):
                self.assertEqual(row['changes'], [dict(old_text=a, new_text=b, count=1)
                                                 for a, b in EXACT_EDITS[row['path']]])
                restored = scope.restore_fixture_source((ROOT / row['path']).read_bytes(), row)
                self.assertEqual(scope.byte_identity(restored), previous['current']['files'][row['path']])
        for name, expected in previous['current']['files'].items():
            if name not in EXACT_EDITS:
                with self.subTest(unchanged=name):
                    self.assertEqual(scope.byte_identity((ROOT / name).read_bytes()), expected)

    def test_old_historical_originals_and_process_pins_are_not_reinterpreted(self):
        previous = json.loads((ROOT / ANCHOR).read_bytes())
        current = scope.load_test_scope(ROOT)
        replacements = dict(pair for edits in EXACT_EDITS.values() for pair in edits)
        for name in ('previous_release', 'reviewed_release', 'accepted_release',
                     'provenance_release', 'maintenance_release', 'execution_release'):
            old, new = previous[name], current[name]
            with self.subTest(binding=name):
                self.assertEqual({k: new[k] for k in ('path', 'bytes', 'sha256')},
                                 {k: old[k] for k in ('path', 'bytes', 'sha256')})
                self.assertEqual([row['path'] for row in new['fixture_exceptions']],
                                 [row['path'] for row in old['fixture_exceptions']])
            for before, after in zip(old['fixture_exceptions'], new['fixture_exceptions']):
                with self.subTest(binding=name, path=before['path']):
                    self.assertEqual(after['original'], before['original'])
                    self.assertEqual(after.get('kind'), before.get('kind'))
                    self.assertEqual(after['changes'], [dict(change, new_text=replacements.get(change['new_text'], change['new_text']))
                                                       for change in before['changes']])
                    restored = scope.restore_fixture_source((ROOT / after['path']).read_bytes(), after)
                    self.assertEqual(scope.byte_identity(restored), before['original'])
        for before, after in zip(previous['fixture_exceptions'], current['fixture_exceptions']):
            self.assertEqual(before['path'], after['path'])
            self.assertEqual(before['original'], after['original'])
            self.assertEqual(after['changes'], [dict(change, new_text=replacements.get(change['new_text'], change['new_text']))
                                               for change in before['changes']])
            self.assertEqual(scope.byte_identity(scope.restore_fixture_source((ROOT / after['path']).read_bytes(), after)),
                             before['original'])
        process_before = next(row for row in previous['execution_release']['fixture_exceptions']
                              if row['path'] == 'tests/test_recorded_execution_release_gate.py')
        process_after = next(row for row in current['execution_release']['fixture_exceptions']
                             if row['path'] == 'tests/test_recorded_execution_release_gate.py')
        self.assertEqual(process_after, process_before)

    def test_metadata_permission_rejects_behavior_schema_path_and_general_version_edits(self):
        current = scope.load_test_scope(ROOT)
        original = next(row for row in current['execution_repair_release']['fixture_exceptions']
                        if row['path'] == 'tests/test_release_test_scope.py')
        for mutation in ('financial', 'schema', 'path', 'version_regex', 'boolean_count'):
            changed = deepcopy(original)
            if mutation == 'financial':
                changed['changes'].append(dict(old_text="self.assertEqual(balance, '7')", new_text="self.assertEqual(balance, '8')", count=1))
            elif mutation == 'schema':
                changed['changes'].append(dict(old_text='self.assertEqual(schema, 6)', new_text='self.assertEqual(schema, 7)', count=1))
            elif mutation == 'path':
                changed['path'] = 'tests/test_stage12_1_process_binding.py'
            elif mutation == 'version_regex':
                changed['changes'][0] = dict(old_text='0.10.1', new_text='0.11.0', count=1)
            else:
                changed['changes'][0]['count'] = True
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'TEST_SCOPE:'):
                scope.validate_replay_fixture_exception(changed)


if __name__ == '__main__':
    unittest.main()

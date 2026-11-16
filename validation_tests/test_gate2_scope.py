"""Finite adversarial controls for the explicit Gate 2 fixture composition."""
from copy import deepcopy
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def helper(root):
    spec = importlib.util.spec_from_file_location('gate2_scope_' + root.name, root / 'scripts/release_test_scope.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Gate2ScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gate2-scope-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = helper(ROOT)
        self.contract = self.scope.load_test_scope(ROOT)
        for name in [*self.contract['current']['files'],
                     *[str(p.relative_to(ROOT)) for p in (ROOT / 'contracts').glob('*.json')],
                     'scripts/release_test_scope.py']:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def test_assertion_ast_serialization_keeps_empty_fields(self):
        node = ast.parse('self.assertEqual(f(), 1)').body[0].value
        self.assertEqual(self.scope.gate2_ast_dump(node).count('keywords=[]'), 2)
        self.assertIn('args=[]', self.scope.gate2_ast_dump(node))

    def test_exact_three_file_composition_preserves_875_ids_and_real_hashes(self):
        result = self.scope.validate_test_files(self.root)
        self.assertEqual((result['expected_count'], result['file_count']), (875, 94))
        self.assertEqual(result['scope_identity'], self.scope.identity())
        self.assertEqual(result['gate2_fixture_exception_identity'], self.scope.gate2_exception_identity())
        self.assertEqual(set(result['gate2_restored_files']), self.scope.GATE2_FIXTURE_PATHS)
        for name in self.scope.GATE2_FIXTURE_PATHS:
            raw = (self.root / name).read_bytes()
            restored = self.scope.restore_gate2_fixture_source(self.root, name, raw)
            self.assertNotEqual(raw, restored)
            self.assertEqual(self.scope.byte_identity(raw)['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(self.scope.byte_identity(restored), self.contract['current']['files'][name])

    def test_changed_current_bytes_reject_for_each_admitted_path(self):
        for name in self.scope.GATE2_FIXTURE_PATHS:
            with self.subTest(path=name):
                target = self.root / name
                original = target.read_bytes()
                target.write_bytes(original + b'\n# unreviewed byte\n')
                with self.assertRaises(ValueError):
                    self.scope.validate_test_files(self.root)
                target.write_bytes(original)

    def test_pre_gate2_bytes_cannot_substitute_for_corrected_fixture(self):
        name = 'tests/test_lab_contract_validation.py'
        target = self.root / name
        target.write_bytes(self.scope.restore_gate2_fixture_source(self.root, name, target.read_bytes()))
        with self.assertRaises(ValueError):
            self.scope.validate_test_files(self.root)

    def test_consistently_rehashed_candidate_cannot_refresh_exception_pin(self):
        path = self.root / self.scope.GATE2_EXCEPTION_PATH
        document = json.loads(path.read_text())
        row = document['files'][0]
        target = self.root / row['path']
        target.write_bytes(target.read_bytes() + b'\n# candidate-controlled\n')
        row['current'] = self.scope.byte_identity(target.read_bytes())
        path.write_text(json.dumps(document, indent=2) + '\n')
        with self.assertRaisesRegex(ValueError, 'pinned identity differs'):
            self.scope.validate_test_files(self.root)

    def test_missing_empty_or_substituted_exception_rejects(self):
        path = self.root / self.scope.GATE2_EXCEPTION_PATH
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises((OSError, ValueError)):
            self.scope.validate_test_files(self.root)
        for replacement in (b'', b'{"files": []}', b'{"files": [{"path": "tests/other.py"}]}'):
            with self.subTest(replacement=replacement):
                path.write_bytes(replacement)
                with self.assertRaises(ValueError):
                    self.scope.validate_test_files(self.root)
        path.write_bytes(original)

    def test_omitted_or_extra_file_rejects(self):
        target = self.root / 'tests/test_lab_contract_validation.py'
        original = target.read_bytes()
        target.unlink()
        with self.assertRaises(ValueError):
            self.scope.validate_test_files(self.root)
        target.write_bytes(original)
        (self.root / 'tests/test_unreviewed.py').write_text('')
        with self.assertRaises(ValueError):
            self.scope.validate_test_files(self.root)

    def test_empty_duplicate_omitted_or_substituted_ids_reject(self):
        ids = self.contract['current']['test_ids']
        for changed in ([], ids[:-1], ids[:-1] + [ids[0]],
                        ids[:-1] + ['test_unreviewed.Unreviewed.test_substituted']):
            with self.subTest(size=len(changed)), self.assertRaises(ValueError):
                self.scope.validate_discovered_ids(changed, self.contract)

    def test_caller_scope_cannot_override_historical_pin(self):
        candidate = deepcopy(self.contract)
        candidate['current']['test_ids'][-1] = 'test_unreviewed.Unreviewed.test_substituted'
        with self.assertRaises(ValueError):
            self.scope.validate_test_files(self.root, candidate)

    def test_historical_cascade_uses_helper_local_contract(self):
        local = helper(self.root)
        row = next(row for row in self.contract['replay_release']['fixture_exceptions']
                   if row['path'] == 'tests/test_execution_replay_scope.py')
        raw = (self.root / row['path']).read_bytes()
        self.assertEqual(local.byte_identity(local.restore_fixture_source(raw, row)), row['original'])
        # The checkout remains valid; corrupting the extracted source's own
        # contract must still prevent historical restoration there.
        (self.root / local.GATE2_EXCEPTION_PATH).write_text('{}\n')
        with self.assertRaisesRegex(ValueError, 'pinned identity differs'):
            local.restore_fixture_source(raw, row)


if __name__ == '__main__':
    unittest.main()

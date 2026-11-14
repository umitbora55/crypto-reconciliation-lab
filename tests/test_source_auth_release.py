"""Narrow Stage 10 optional-dependency, distribution and test-scope boundaries."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('auth_release_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load('verify_release')
build = load('build_release')
scope = load('release_test_scope')


class SourceAuthReleaseTests(unittest.TestCase):
    def test_core_auth_absence_requires_availability_and_distribution_absence(self):
        base = {'auth_imported': [], 'auth_available': {'cryptography': False, 'cffi': False, 'pycparser': False},
                'dependencies': {}}
        verify.validate_auth_absent(base)
        for mutation in ({'auth_imported': ['cryptography']},
                         {'auth_available': {'cryptography': True, 'cffi': False, 'pycparser': False}},
                         {'dependencies': {'cryptography': {'version': '50.0.2'}}},
                         {'auth_available': {}}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify.validate_auth_absent(base | mutation)

    def test_auth_only_requires_pinned_transitives_without_ai(self):
        dependencies = {name: {'version': version} for name, version in
                        (('cryptography', '50.0.2'), ('cffi', '2.1.1'), ('pycparser', '3.12'))}
        base = {'auth_available': {'cryptography': True, 'cffi': True, 'pycparser': True},
                'optional_imported': [], 'optional_available': {'sklearn': False, 'numpy': False, 'scipy': False},
                'dependencies': dependencies}
        verify.validate_auth_pins(base, ROOT)
        verify.validate_core_probe(base)
        for name in dependencies:
            changed = deepcopy(base)
            changed['dependencies'][name]['version'] = '0.0.0'
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'auth pin mismatch'):
                verify.validate_auth_pins(changed, ROOT)
        changed = deepcopy(base); changed['optional_available']['numpy'] = True
        with self.assertRaises(ValueError):
            verify.validate_core_probe(changed)

    def test_auth_resource_is_allowlisted_but_arbitrary_json_is_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            for index, name in enumerate(('crypto_reconciliation_lab/source_auth/experiment_scope_v1.json',
                                          'crypto_reconciliation_lab/source_auth/unreviewed.json')):
                archive = Path(temporary) / f'{index}.whl'
                with zipfile.ZipFile(archive, 'w') as output:
                    output.writestr(name, b'{}')
                if index == 0:
                    self.assertEqual(verify.wheel_manifest(archive)[name]['bytes'], 2)
                else:
                    with self.assertRaisesRegex(ValueError, 'unexpected package data'):
                        verify.wheel_manifest(archive)

    def test_auth_contract_and_pins_are_required_source_inputs(self):
        required = {'requirements-auth.txt', 'contracts/release-test-scope-0.8.0.json',
                    'contracts/source-auth-scope-v1.json',
                    'crypto_reconciliation_lab/source_auth/experiment_scope_v1.json'}
        self.assertLessEqual(required, build.REQUIRED)
        names = build.selected_files(ROOT)
        self.assertLessEqual(required, set(names))
        self.assertIn('tests/source_auth_legacy_fixtures.py', names)

    def test_historical_recovery_bytes_and_release_remain_pinned(self):
        relative = 'crypto_reconciliation_lab/admission/recovery_scope_v2.json'
        data = (ROOT / relative).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         '4b0f84fa393a7dceaacb4c62afa35a8a9aa2cda8a70c324b2d77a56711a18d71')
        self.assertEqual(json.loads(data)['release'], '0.7.1')

    def test_current_scope_retains_all_472_prior_identities(self):
        current = scope.load_test_scope(ROOT)
        baseline = json.loads((ROOT / 'contracts/release-test-scope-0.7.1.json').read_text())
        self.assertEqual(len(baseline['current']['test_ids']), 472)
        self.assertLessEqual(set(baseline['current']['test_ids']), set(current['current']['test_ids']))
        self.assertEqual(current['baseline']['sha256'],
                         '2e21ae9f60ec7163af140d9f8e2eb91f33d3492e6b3edb1b3b4a86430a736a7e')
        self.assertEqual(set(current['current']['test_ids']),
                         set(baseline['current']['test_ids']) | set(current['additions']['test_ids']))

    def test_historical_schema4_exception_cannot_change_assertions(self):
        contract = scope.load_test_scope(ROOT)
        exception = next(row for row in contract['fixture_exceptions']
                         if row['path'] == 'tests/test_admission_migrations.py')
        restored = scope.restore_fixture_source((ROOT / exception['path']).read_bytes(), exception)
        self.assertEqual(scope.byte_identity(restored), exception['original'])
        changed = deepcopy(exception)
        changed['changes'][-1]['new_text'] += '\n        self.assertEqual(run.schema_version, 5)'
        with self.assertRaisesRegex(ValueError, 'exceeds fixed authorization'):
            scope.validate_fixture_exception(changed)

    def test_core_missing_auth_cannot_claim_success_after_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            gate = verify.Verification(Path(temporary) / 'gate', 'core')
            def misleading(*args, **kwargs):
                (gate.output / 'core-auth-must-not-exist').mkdir()
                (gate.output / 'logs/core-auth-unavailable.stderr.txt').write_text('AUTH_DEPENDENCY')
            with patch.object(gate, 'run', side_effect=misleading):
                with self.assertRaisesRegex(ValueError, 'before creating output'):
                    verify.core_auth_denied(gate, 'not-executed')

"""S6-F2 regression boundaries: real release entry points and existing APIs."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

PROJECT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location('financial_scope_test_' + name,
                                                  PROJECT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load_script('verify_release')
builder = load_script('build_release')
REFERENCE = 'docs/stage6/financial-reference.json'


class ReleaseFinancialScopeTests(unittest.TestCase):
    def owned_source(self, parent):
        source = parent / 'source'
        for name in builder.selected_files(PROJECT):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / name, target)
        wheel = parent / 'placeholder.whl'
        # A regular safe wheel member lets preflight reach financial validation.
        # It must never reach an install: this is not an installable wheel fixture.
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('crypto_reconciliation_lab/__init__.py', b'')
        return source, wheel

    def document(self):
        return json.loads((PROJECT / REFERENCE).read_text())

    def assert_preflight_rejects(self, document, profile='core', raw=None):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, wheel = self.owned_source(parent)
            path = source / REFERENCE
            path.write_bytes(raw if raw is not None else
                             (json.dumps(document, indent=2, sort_keys=True) + '\n').encode())
            called = []
            def expensive_boundary(name, *args, **kwargs):
                called.append(name)
                raise ValueError('EXPENSIVE_OPERATION_REACHED: ' + name)
            output = parent / 'output'
            with patch.object(verify.Verification, 'run', side_effect=expensive_boundary), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = verify.main(['--profile', profile, '--source', str(source),
                                    '--wheel', str(wheel), '--output', str(output)])
            report = json.loads((output / 'verification.json').read_text())
            self.assertEqual(code, 1)
            self.assertEqual(report['status'], 'ERROR')
            self.assertEqual(called, [], 'invalid reference reached an expensive release operation')
            self.assertIn('FINANCIAL_REFERENCE:', report['error'])
            self.assertNotIn('full_bytes_and_run_ids_equal', json.dumps(report))

    def test_general_empty_comparison_rejects_even_missing_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                verify.compare_reports(Path(temporary) / 'not-present', {'files': {}})

    def test_all_empty_maps_with_unchanged_declared_total_reject(self):
        document = self.document()
        for group in document['reports'].values():
            group['files'] = {}
        self.assertEqual(document['file_count'], 373)
        self.assert_preflight_rejects(document)

    def test_partial_group_rejects_before_full_profile_install(self):
        document = self.document()
        del document['reports']['matrix']
        self.assert_preflight_rejects(document, 'full')

    def test_one_required_file_missing_rejects(self):
        document = self.document()
        document['reports']['stage1']['files'].pop('clean/initial.json')
        self.assert_preflight_rejects(document)

    def test_same_count_wrong_name_rejects(self):
        document = self.document()
        files = document['reports']['stage2']['files']
        files['unrelated/initial.json'] = files.pop('void_deposit/original.json')
        self.assertEqual(len(files), 36)
        self.assert_preflight_rejects(document)

    def test_real_json_types_and_exact_matrix_settings_are_mandatory(self):
        for path, value in ((('file_count',), True), (('schema_version',), '3'),
                            (('matrix', 'cases'), 69.0), (('matrix', 'evaluations'), '162'),
                            (('matrix', 'seeds'), [11, 29, True]),
                            (('matrix', 'events'), 101), (('matrix', 'investors'), 7),
                            (('matrix', 'zero_counters'), ['wrong_state'] * 10),
                            (('demo_evaluations', 'stage1'), 6.0), (('version',), '0.6.0'),
                            (('format',), 'financial-reference-v2')):
            with self.subTest(path=path, value=value):
                document = self.document()
                target = document
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assert_preflight_rejects(document)

    def test_unsafe_names_reject_without_accessing_output_files(self):
        for name in ('../escape.json', '/absolute.json', 'C:/escape.json', 'a\\b.json',
                     'a//b.json', './report.json'):
            with self.subTest(name=name):
                document = self.document()
                files = document['reports']['stage1']['files']
                files[name] = files.pop('clean/initial.json')
                self.assert_preflight_rejects(document)

    def test_bad_hash_size_and_same_count_group_exchange_reject(self):
        for field, value in (('sha256', 'g' * 64), ('sha256', '0' * 64),
                             ('bytes', True), ('bytes', -1), ('bytes', '52322')):
            with self.subTest(field=field, value=value):
                document = self.document()
                document['reports']['stage1']['files']['clean/initial.json'][field] = value
                self.assert_preflight_rejects(document)
        document = self.document()
        a, b = document['reports']['stage1']['files'], document['reports']['stage2']['files']
        a['clean/initial.json'], b['void_deposit/original.json'] = \
            b['void_deposit/original.json'], a['clean/initial.json']
        self.assert_preflight_rejects(document)

    def test_reference_raw_identity_is_fixed_outside_its_document(self):
        raw = (PROJECT / REFERENCE).read_bytes() + b' '
        self.assertEqual(json.loads(raw), self.document())
        self.assert_preflight_rejects(None, raw=raw)

    def test_valid_fixed_reference_reaches_environment_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, wheel = self.owned_source(parent)
            called = []
            def boundary(name, *args, **kwargs):
                called.append(name)
                raise ValueError('VALID_REFERENCE_BOUNDARY')
            output = parent / 'output'
            with patch.object(verify.Verification, 'run', side_effect=boundary), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = verify.main(['--profile', 'core', '--source', str(source),
                                    '--wheel', str(wheel), '--output', str(output)])
            self.assertEqual(code, 1)
            self.assertEqual(called, ['create-environment'])
            report = json.loads((output / 'verification.json').read_text())
            self.assertEqual(report['error'], 'VALID_REFERENCE_BOUNDARY')

    def test_real_core_and_full_cli_reject_empty_reference_before_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, wheel = self.owned_source(parent)
            document = self.document()
            for group in document['reports'].values():
                group['files'] = {}
            (source / REFERENCE).write_text(json.dumps(document))
            for profile in ('core', 'full'):
                with self.subTest(profile=profile):
                    output = parent / profile
                    result = subprocess.run([sys.executable, '-B', '-I', source / 'scripts/verify_release.py',
                        '--profile', profile, '--source', source, '--wheel', wheel, '--output', output],
                        cwd=parent, capture_output=True, text=True, timeout=30,
                        env=verify.clean_environment())
                    report = json.loads((output / 'verification.json').read_text())
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(report['status'], 'ERROR')
                    self.assertEqual(report['commands'], [], 'real CLI attempted expensive work')
                    self.assertIn('FINANCIAL_REFERENCE:', report['error'])
                    self.assertFalse((output / 'environment').exists())

    def test_real_no_source_cli_rejects_bad_reference_before_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, _wheel = self.owned_source(parent)
            document = self.document()
            document['reports']['stage1']['files'].pop('clean/initial.json')
            (source / REFERENCE).write_text(json.dumps(document))
            output = parent / 'output'
            result = subprocess.run([sys.executable, '-B', '-I', source / 'scripts/verify_release.py',
                '--profile', 'core', '--output', output], cwd=parent,
                capture_output=True, text=True, timeout=30, env=verify.clean_environment())
            report = json.loads((output / 'verification.json').read_text())
            self.assertEqual(result.returncode, 1)
            self.assertEqual(report['status'], 'ERROR')
            self.assertEqual(report['commands'], [], 'real CLI attempted build before reference validation')
            self.assertIn('FINANCIAL_REFERENCE:', report['error'])
            self.assertFalse((output / 'build').exists())

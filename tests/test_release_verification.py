"""Failure-oriented checks for the portable release gate; no release or ML replay."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import stat
import zipfile
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('portable_release_verification', PROJECT / 'scripts/verify_release.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class ReleaseVerificationTests(unittest.TestCase):
    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'existing'
            output.mkdir()
            sentinel = output / 'sentinel'
            sentinel.write_bytes(b'unchanged')
            with self.assertRaises(FileExistsError):
                verify.Verification(output, 'core')
            self.assertEqual(sentinel.read_bytes(), b'unchanged')
            self.assertEqual(list(output.iterdir()), [sentinel])

    def test_failed_command_is_recorded_and_stops_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            gate = verify.Verification(Path(temporary) / 'output', 'core')
            with patch.object(verify.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)):
                with self.assertRaisesRegex(ValueError, 'received 7'):
                    gate.run('failure', [sys.executable, '-c', 'raise SystemExit(7)'])
            record = json.loads((gate.output / 'verification.json').read_text())
            self.assertEqual(record['commands'][0]['exit_code'], 7)
            self.assertEqual(record['commands'][0]['status'], 'ERROR')

    def test_empty_or_truncated_discovery_cannot_pass(self):
        base = dict(status='PASS', discovered=355, executed=355, skips=0, failures=0, errors=0, unexpected_successes=0)
        for fields in ({'discovered': 0, 'executed': 0}, {'executed': 354}, {'discovered': 354, 'executed': 354}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                verify.validate_tests(base | fields)

    def test_skipped_or_failed_tests_cannot_pass(self):
        base = dict(status='PASS', discovered=355, executed=355, skips=0, failures=0, errors=0, unexpected_successes=0)
        for field in ('skips', 'failures', 'errors', 'unexpected_successes', 'expected_failures'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify.validate_tests(base | {field: 1})

    def test_no_ai_requires_absence_not_just_no_import(self):
        base = dict(optional_imported=[], optional_available={'sklearn': False, 'numpy': False, 'scipy': False}, dependencies={})
        verify.validate_core_probe(base)
        for changed in ({'optional_imported': ['numpy']}, {'optional_available': {'numpy': True}},
                        {'dependencies': {'scikit-learn': {'version': '1.9.1'}}}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                verify.validate_core_probe(base | changed)

    def test_financial_byte_changes_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'report.json'
            path.write_bytes(b'{"amount":"1"}\n')
            reference = {'files': {'report.json': verify.digest(path)}}
            self.assertEqual(verify.compare_reports(root, reference)['count'], 1)
            path.write_bytes(b'{"amount":"2"}\n')
            with self.assertRaisesRegex(ValueError, 'financial report changed'):
                verify.compare_reports(root, reference)

    def test_partial_source_wheel_arguments_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'untouched'
            with self.assertRaises(SystemExit) as failure:
                verify.main(['--profile', 'full', '--output', str(target), '--source', temporary])
            self.assertEqual(failure.exception.code, 2)
            self.assertFalse(target.exists())

    def test_core_financial_request_fails_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'untouched'
            with self.assertRaises(SystemExit) as failure:
                verify.main(['--profile', 'core', '--output', str(target), '--financial'])
            self.assertEqual(failure.exception.code, 2)
            self.assertFalse(target.exists())

    def test_unsafe_wheel_members_are_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            for number, (name, mode) in enumerate((
                ('../escape.py', stat.S_IFREG), ('C:/escape.py', stat.S_IFREG),
                ('crypto_reconciliation_lab\\escape.py', stat.S_IFREG),
                ('crypto_reconciliation_lab/link.py', stat.S_IFLNK),
                ('crypto_reconciliation_lab/pipe.py', stat.S_IFIFO),
                ('crypto_reconciliation_lab/customer.sqlite3', stat.S_IFREG),
                ('unrelated/install.py', stat.S_IFREG))):
                wheel = Path(temporary) / f'{number}.whl'
                info = zipfile.ZipInfo(name)
                info.external_attr = (mode | 0o600) << 16
                with zipfile.ZipFile(wheel, 'w') as archive:
                    archive.writestr(info, b'content')
                with self.subTest(name=name), self.assertRaises(ValueError):
                    verify.wheel_manifest(wheel)
